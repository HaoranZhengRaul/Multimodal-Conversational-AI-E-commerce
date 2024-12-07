# -*- coding: utf-8 -*-
"""app.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1Tg4a0JvCLZOhgL9lW5B9gGtFWKZZqLTk
"""

import streamlit as st
import faiss
import numpy as np
import pandas as pd
from transformers import CLIPProcessor, CLIPModel
from PIL import Image
import requests
import torch
import openai
import os

# Load the CLIP model and processor
@st.cache_resource
def load_clip_model():
    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
    processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
    return model, processor

clip_model, clip_processor = load_clip_model()

# Helper function to download files from GitHub
def download_file(url, save_path):
    response = requests.get(url, stream=True)
    if response.status_code == 200:
        with open(save_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)
        return save_path
    else:
        raise Exception(f"Failed to download {url}. Status code: {response.status_code}")

# Load FAISS indices
@st.cache_resource
def load_faiss_indices():
    indices = {
        "text_only": "https://raw.githubusercontent.com/HaoranZhengRaul/Multimodal-Conversational-AI-E-commerce/main/app/text_only.index",
        "image_only": "https://raw.githubusercontent.com/HaoranZhengRaul/Multimodal-Conversational-AI-E-commerce/main/app/image_only.index",
        "multimodal_embeddings": "https://raw.githubusercontent.com/HaoranZhengRaul/Multimodal-Conversational-AI-E-commerce/main/app/multimodal_embeddings.index",
    }
    temp_dir = "temp_indices"
    os.makedirs(temp_dir, exist_ok=True)

    loaded_indices = {}
    for name, url in indices.items():
        save_path = os.path.join(temp_dir, f"{name}.index")
        if not os.path.exists(save_path):
            download_file(url, save_path)
        try:
            loaded_indices[name] = faiss.read_index(save_path)
        except Exception as e:
            st.error(f"Failed to load FAISS index for {name}: {e}")

    return (
        loaded_indices.get("text_only"),
        loaded_indices.get("image_only"),
        loaded_indices.get("multimodal_embeddings"),
    )

text_index, image_index, full_index = load_faiss_indices()

# Load dataset
@st.cache_resource
def load_dataset():
    url = "https://raw.githubusercontent.com/HaoranZhengRaul/Multimodal-Conversational-AI-E-commerce/main/app/final_dataset.csv"
    return pd.read_csv(url)

final_dataset = load_dataset()

# Set OpenAI API key
openai.api_key = st.secrets["OPENAI_API_KEY"]

# Helper functions
def preprocess_image(image):
    """Preprocess an image for CLIP."""
    return clip_processor(images=image, return_tensors="pt")

def generate_text_embeddings(texts):
    """Generate text embeddings using CLIP."""
    inputs = clip_processor(text=texts, return_tensors="pt", padding=True, truncation=True)
    with torch.no_grad():
        return clip_model.get_text_features(**inputs).cpu().numpy()

def generate_image_embeddings(images):
    """Generate image embeddings using CLIP."""
    embeddings = []
    for image in images:
        inputs = preprocess_image(image)
        with torch.no_grad():
            embeddings.append(clip_model.get_image_features(**inputs).cpu().numpy())
    return np.vstack(embeddings)

def generate_response_gpt4(query, retrieved_items):
    """Generate a conversational response using GPT-4."""
    if retrieved_items.empty:
        return f"Sorry, I couldn't find any relevant products for your query: {query}"

    # Create a structured context from retrieved items
    context = "\n".join(
        [
            f"{i+1}. {row['Product Name_Cleaned']}: {row['About Product_Cleaned']} "
            f"(Category: {row['Category_Cleaned']}, Price: {row['Selling Price_Cleaned']}, "
            f"Image URL: {row['Image']})"
            for i, row in retrieved_items.iterrows()
        ]
    )

    # Create GPT-4 prompt
    prompt = f"""
    You are a helpful assistant recommending products based on user queries.

    Context:
    Here are some products relevant to the user's query:
    {context}

    Based on the query, recommend the most suitable product(s) and explain why they meet the user's needs.
    If the query asks for a specific product image, include the image URL in the response.

    Question: {query}
    Answer:
    """

    # Generate response using GPT-4
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a friendly, knowledgeable assistant helping users find products."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=300,
        temperature=0.7,
    )
    return response['choices'][0]['message']['content']

# Streamlit app layout
st.title("Multimodal Product Search and Recommendation")

# Query input
query_type = st.radio("Select Query Type:", ["Text", "Image", "Multimodal"])
query = st.text_input("Enter your query (for text and multimodal queries):")
uploaded_file = st.file_uploader("Upload an image (for image and multimodal queries):")

if st.button("Search"):
    try:
        # Process text query
        text_embedding = None
        image_embedding = None

        if query_type in ["Text", "Multimodal"] and query:
            text_embedding = generate_text_embeddings([query])

        if query_type in ["Image", "Multimodal"] and uploaded_file:
            image = Image.open(uploaded_file).convert("RGB")
            image_embedding = generate_image_embeddings([image])

        # Combine embeddings for multimodal query
        if query_type == "Multimodal" and text_embedding is not None and image_embedding is not None:
            multimodal_embedding = np.hstack([text_embedding, image_embedding])
            index_to_use = full_index
        elif query_type == "Text" and text_embedding is not None:
            multimodal_embedding = text_embedding
            index_to_use = text_index
        elif query_type == "Image" and image_embedding is not None:
            multimodal_embedding = image_embedding
            index_to_use = image_index
        else:
            st.error("Please provide a valid query!")
            st.stop()

        # Perform search
        distances, indices = index_to_use.search(multimodal_embedding, k=5)
        retrieved_items = final_dataset.iloc[indices.flatten()]

        # Display results
        st.subheader("Retrieved Results")
        for _, row in retrieved_items.iterrows():
            st.markdown(f"**{row['Product Name_Cleaned']}**")
            st.markdown(f"Category: {row['Category_Cleaned']}")
            st.markdown(f"Price: {row['Selling Price_Cleaned']}")
            st.markdown(f"[Product Link]({row['Product Url']})")
            st.image(row['Image'], caption=row['Product Name_Cleaned'], use_column_width=True)

        # Generate GPT-4 response
        gpt_response = generate_response_gpt4(query or "image-based query", retrieved_items)
        st.subheader("GPT-4 Response")
        st.write(gpt_response)

    except Exception as e:
        st.error(f"An error occurred: {e}")
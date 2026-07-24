import os
from typing import List, Dict
import chromadb
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_community.embeddings.sentence_transformer import SentenceTransformerEmbeddings
from app.services.embedding_service import CHROMA_STORAGE_DIR
from app.core.config import settings

# 1. Initialize the same Embedding Model we used in Phase 5
embedding_function = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

# 2. Connect to our local ChromaDB
chroma_client = chromadb.PersistentClient(path=CHROMA_STORAGE_DIR)

# 3. Initialize the LLM (OpenAI by default)
# You could easily swap this for `from langchain_community.llms import Ollama` 
# and use `llm = Ollama(model="llama3")` if you are running Ollama locally.
llm = ChatNVIDIA(
    model="deepseek-ai/deepseek-v4-flash", 
    temperature=0.2, # Low temperature because we want factual code answers, not creative writing
    api_key=settings.NVIDIA_API_KEY 
)

def query_repository(repo_id: str, question: str) -> str:
    """
    Executes a RAG query against a specific repository.
    """
    collection_name = f"repo_{repo_id.replace('-', '')}"
    
    try:
        collection = chroma_client.get_collection(name=collection_name)
    except Exception:
        return "Error: Repository embeddings not found. Please ensure the repository has been fully processed."

    # --- STEP 1: RETRIEVAL ---
    # We turn the user's question into a vector and search for the top 5 closest chunks
    print(f"Searching ChromaDB for: '{question}'")
    
    # We must embed the query text manually to match our ChromaDB setup
    query_embedding = embedding_function.embed_query(question)
    
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=5, # Get the top 5 most relevant code chunks
        include=["documents", "metadatas"]
    )

    if not results['documents'][0]:
        return "I couldn't find any relevant code in this repository to answer your question."

    # --- STEP 2: CONTEXT BUILDING ---
    # We format the retrieved code chunks into a single readable string for the LLM
    context_blocks = []
    for doc, metadata in zip(results['documents'][0], results['metadatas'][0]):
        # The metadata helps the LLM know *where* this code came from
        file_path = metadata.get('file_path', 'Unknown file')
        chunk_type = metadata.get('chunk_type', 'code')
        
        # We wrap the code in backticks so the LLM understands it is code
        block = f"--- File: {file_path} ({chunk_type}) ---\n```python\n{doc}\n```"
        context_blocks.append(block)

    full_context = "\n\n".join(context_blocks)

    # --- STEP 3: THE PROMPT ---
    # We explicitly instruct the LLM to only answer based on the provided context
    system_prompt = f"""You are a senior AI software architect assisting a developer.
Your task is to answer the user's question about their codebase using ONLY the provided code snippets.

CRITICAL RULES:
1. If the answer is not contained in the provided code, say "I don't have enough context in the retrieved code to answer that." Do not guess.
2. Always cite the file names when explaining the code.
3. Keep your explanation concise and technical.

--- REPOSITORY CONTEXT ---
{full_context}
"""

    # --- STEP 4: GENERATION ---
    print("Context built. Querying LLM...")
    try:
        # We pass the system prompt and the user's question to the LLM
        messages = [
            ("system", system_prompt),
            ("human", question)
        ]
        response = llm.invoke(messages)
        return response.content
        
    except Exception as e:
        return f"Error communicating with the LLM: {str(e)}"
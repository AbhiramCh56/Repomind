import os
from typing import List, Dict
import chromadb
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_groq import ChatGroq
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from app.models.chat import ChatMessage
from app.services.embedding_service import CHROMA_STORAGE_DIR
from app.core.config import settings

# 1. Initialize the same Embedding Model we used in Phase 5
embedding_function = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

# 2. Connect to our local ChromaDB
chroma_client = chromadb.PersistentClient(path=CHROMA_STORAGE_DIR)

# 3. Initialize the LLM provider (configurable via LLM_PROVIDER / .env)
def _init_llm():
    provider = settings.LLM_PROVIDER.lower()

    if provider == "groq":
        if not settings.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY is not set in the environment.")
        return ChatGroq(
            model="openai/gpt-oss-20b",
            temperature=0.2, # Low temperature because we want factual code answers, not creative writing
            api_key=settings.GROQ_API_KEY
        )

    if provider == "nvidia":
        if not settings.NVIDIA_API_KEY:
            raise ValueError("NVIDIA_API_KEY is not set in the environment.")
        return ChatNVIDIA(
            model="nvidia/nemotron-3.5-lightning-30b-a3b",
            temperature=0.2, # Low temperature because we want factual code answers, not creative writing
            api_key=settings.NVIDIA_API_KEY
        )

    raise ValueError(f"Unsupported LLM_PROVIDER '{provider}'. Use 'nvidia' or 'groq'.")

# Initialize the LLM once at import time
llm = _init_llm()



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


def get_llm():
    """Return the configured LLM instance."""
    return llm


def get_retriever(repo_id: str):
    """
    Build a LangChain retriever over the ChromaDB collection for a repository.
    """
    from langchain_chroma import Chroma

    collection_name = f"repo_{str(repo_id).replace('-', '')}"

    try:
        # Wrap the existing ChromaDB collection with a LangChain-compatible vectorstore
        vectorstore = Chroma(
            client=chroma_client,
            collection_name=collection_name,
            embedding_function=embedding_function,
        )
        return vectorstore.as_retriever(search_kwargs={"k": 5})
    except Exception:
        raise ValueError(
            "Repository embeddings not found. Please ensure the repository has "
            "been fully processed."
        )


def _build_chain(db, session_id: int, question: str, retriever, llm):
  """Shared history loading + context retrieval + prompt construction."""
  # 1. Retrieve history from PostgreSQL
  raw_history = (
      db.query(ChatMessage)
      .filter(ChatMessage.session_id == session_id)
      .order_by(ChatMessage.created_at.asc())
      .all()
  )

  chat_history = []
  for msg in raw_history:
    if msg.role == "human":
      chat_history.append(HumanMessage(content=msg.content))
    else:
      chat_history.append(AIMessage(content=msg.content))

  # 2. Retrieve vector store context
  relevant_docs = retriever.invoke(question)
  context = "\n\n".join([doc.page_content for doc in relevant_docs])

  # 3. Build prompt with history buffer
  prompt = ChatPromptTemplate.from_messages([
      (
          "system",
          (
              "You are an expert software engineer analyzing a codebase. Use"
              " the codebase context and previous conversation history to answer"
              " accurately.\n\nContext:\n{context}"
          ),
      ),
      MessagesPlaceholder(variable_name="chat_history"),
      ("human", "{question}"),
  ])

  # 4. Wire up the chain
  chain = prompt | llm
  inputs = {
      "context": context,
      "chat_history": chat_history,
      "question": question,
  }
  return chain, inputs


def ask_codebase_with_history(
    db, session_id: int, question: str, retriever, llm
) -> str:
  chain, inputs = _build_chain(db, session_id, question, retriever, llm)

  response = chain.invoke(inputs)
  return response.content


def ask_codebase_with_history_stream(
    db, session_id: int, question: str, retriever, llm
):
  """
  Generator that yields the running answer text token by token and persists
  the complete AI response to the conversation when generation finishes.
  """
  chain, inputs = _build_chain(db, session_id, question, retriever, llm)

  full_response = ""
  for chunk in chain.stream(inputs):
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
      full_response += content
    elif isinstance(content, list):
      for item in content:
        if isinstance(item, dict):
          full_response += item.get("text", "")
        elif isinstance(item, str):
          full_response += item
    else:
      full_response += str(content)
    yield full_response

  # Persist the complete AI response to the conversation
  db.add(ChatMessage(session_id=session_id, role="ai", content=full_response))
  db.commit()
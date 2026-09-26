import logging

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_groq import ChatGroq
from langchain_nvidia_ai_endpoints import ChatNVIDIA

from app.core.config import settings
from app.models.chat import ChatMessage
from app.services.embedding_service import (
    get_chroma_client,
    get_collection_name,
    get_embedding_function,
)

logger = logging.getLogger(__name__)

RETRIEVAL_TOP_K = 5

_llm = None


def _build_llm():
    provider = settings.LLM_PROVIDER.lower()

    if provider == "groq":
        if not settings.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY is not set in the environment.")
        return ChatGroq(
            model=settings.LLM_MODEL_GROQ,
            temperature=settings.LLM_TEMPERATURE,
            api_key=settings.GROQ_API_KEY,
        )

    if provider == "nvidia":
        if not settings.NVIDIA_API_KEY:
            raise ValueError("NVIDIA_API_KEY is not set in the environment.")
        return ChatNVIDIA(
            model=settings.LLM_MODEL_NVIDIA,
            temperature=settings.LLM_TEMPERATURE,
            api_key=settings.NVIDIA_API_KEY,
        )

    raise ValueError(
        f"Unsupported LLM_PROVIDER '{provider}'. Use 'nvidia' or 'groq'."
    )


def get_llm():
    """Return the configured LLM, building it on first use."""
    global _llm
    if _llm is None:
        logger.info("Initializing %s LLM", settings.LLM_PROVIDER)
        _llm = _build_llm()
    return _llm


def get_retriever(repo_id: str):
    """
    Build a LangChain retriever over the ChromaDB collection for a repository.
    """
    from langchain_chroma import Chroma

    try:
        vectorstore = Chroma(
            client=get_chroma_client(),
            collection_name=get_collection_name(repo_id),
            embedding_function=get_embedding_function(),
        )
        return vectorstore.as_retriever(search_kwargs={"k": RETRIEVAL_TOP_K})
    except Exception as exc:
        raise ValueError(
            "Repository embeddings not found. Please ensure the repository has "
            f"been fully processed. ({exc})"
        ) from exc


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

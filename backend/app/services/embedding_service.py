import os
from sqlalchemy.orm import Session
import chromadb
from chromadb.config import Settings
from langchain_huggingface import HuggingFaceEmbeddings
from app.models.chunk import Chunk
from app.models.file import File
from app.models.repository import Repository

# We store the vector database locally on the server disk
CHROMA_STORAGE_DIR = os.getenv("CHROMA_STORAGE_DIR", "/tmp/repomind_chroma")
os.makedirs(CHROMA_STORAGE_DIR, exist_ok=True)

# Initialize ChromaDB in persistent mode
chroma_client = chromadb.PersistentClient(path=CHROMA_STORAGE_DIR)

# Load the open-source HuggingFace embedding model locally (Runs on CPU, free)
# This converts code/text into 384-dimensional vectors
embedding_function = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

def embed_repository_chunks(repo_id: str, db: Session):
    """
    Fetches all parsed chunks for a repository from PostgreSQL,
    generates embeddings, and stores them in ChromaDB.
    """
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        print(f"Repository {repo_id} not found for embedding.")
        return

    print(f"Starting embedding process for {repo.full_name}...")

    # We join File and Chunk tables to get the file path for metadata
    chunks_with_files = db.query(Chunk, File).join(File, Chunk.file_id == File.id)\
                          .filter(File.repository_id == repo_id).all()

    if not chunks_with_files:
        print(f"No chunks found for {repo.full_name}. Skipping embedding.")
        return

    # We create a unique collection for this repository. 
    # This acts as a hard boundary, ensuring we don't accidentally query code from another repo.
    collection_name = f"repo_{repo_id.replace('-', '')}"
    
    # Get or create the collection
    try:
        collection = chroma_client.get_or_create_collection(
            name=collection_name,
            metadata={"description": f"Embeddings for {repo.full_name}"}
        )
    except Exception as e:
        print(f"Error creating ChromaDB collection: {e}")
        return

    # ChromaDB performs best when we insert in batches (e.g., 100 at a time)
    documents = []
    metadatas = []
    ids = []

    for chunk, file in chunks_with_files:
        # We enrich the code chunk with its file path so the LLM knows WHERE the code lives
        content_to_embed = f"File: {file.file_path}\nCode:\n{chunk.content}"
        
        documents.append(content_to_embed)
        ids.append(str(chunk.id))
        
        # This metadata allows us to perform precise filtering later
        # e.g., "Only search inside 'function' chunks in 'backend/main.py'"
        metadatas.append({
            "file_path": file.file_path,
            "language": file.language,
            "chunk_type": chunk.chunk_type,
            "name": chunk.name or "unknown",
            "start_line": chunk.start_line or 0
        })

    # Insert in batches of 100 to avoid memory spikes
    batch_size = 100
    for i in range(0, len(documents), batch_size):
        try:
            # We must use the LangChain embedding function to convert text to vectors manually
            # because we are interacting with the Chroma client directly here.
            batch_docs = documents[i:i+batch_size]
            batch_embeddings = embedding_function.embed_documents(batch_docs)
            
            collection.add(
                documents=batch_docs,
                embeddings=batch_embeddings,
                metadatas=metadatas[i:i+batch_size],
                ids=ids[i:i+batch_size]
            )
            print(f"Embedded batch {i//batch_size + 1}/{(len(documents)//batch_size) + 1}...")
        except Exception as e:
            print(f"Error embedding batch: {e}")

    print(f"Successfully embedded {len(documents)} chunks for {repo.full_name} into ChromaDB!")
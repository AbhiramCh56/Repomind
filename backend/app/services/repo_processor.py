import os
import pathspec
from sqlalchemy.orm import Session
from app.models.repository import Repository
from app.models.file import File

# A sensible default list of files/directories to ignore
DEFAULT_IGNORE_PATTERNS = [
    ".git/", "node_modules/", "venv/", "env/", "__pycache__/",
    "dist/", "build/", "out/", ".next/", "coverage/",
    "*.jpg", "*.jpeg", "*.png", "*.gif", "*.ico", "*.svg", "*.webp",
    "*.mp4", "*.mp3", "*.wav",
    "*.pdf", "*.zip", "*.tar", "*.gz", "*.rar",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml"
]

# A simple map to detect language based on extension
LANGUAGE_MAP = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "React (JavaScript)",
    ".ts": "TypeScript",
    ".tsx": "React (TypeScript)",
    ".md": "Markdown",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".html": "HTML",
    ".css": "CSS",
    ".sh": "Shell",
    ".toml": "TOML",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".cpp": "C++",
    ".c": "C",
    ".h": "C Header"
}

def get_ignore_spec(repo_path: str) -> pathspec.PathSpec:
    """Reads .gitignore if it exists and combines it with our defaults."""
    patterns = list(DEFAULT_IGNORE_PATTERNS)
    
    gitignore_path = os.path.join(repo_path, ".gitignore")
    if os.path.exists(gitignore_path):
        with open(gitignore_path, "r", encoding="utf-8", errors="ignore") as f:
            patterns.extend(f.readlines())
            
    return pathspec.PathSpec.from_lines(pathspec.patterns.GitWildMatchPattern, patterns)

def detect_language(filename: str) -> str:
    """Guess the programming language from the extension."""
    if filename == "Dockerfile":
        return "Dockerfile"
    if filename == "Makefile":
        return "Makefile"
        
    _, ext = os.path.splitext(filename)
    return LANGUAGE_MAP.get(ext.lower(), "Unknown")

def process_repository_files(repo_id: str, db: Session):
    """
    Walks the cloned repository directory, filters ignored files,
    and creates a File record in the database for each valid file.
    """
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo or not repo.local_path:
        return

    # Delete any existing files for this repo (useful if we re-sync later)
    db.query(File).filter(File.repository_id == repo.id).delete()
    db.commit()

    spec = get_ignore_spec(repo.local_path)
    file_records_to_insert = []

    for root, dirs, files in os.walk(repo.local_path):
        # Calculate the relative path from the root of the repo
        rel_root = os.path.relpath(root, repo.local_path)
        if rel_root == ".":
            rel_root = ""

        # Remove ignored directories *in place* so os.walk doesn't even traverse them!
        dirs[:] = [d for d in dirs if not spec.match_file(os.path.join(rel_root, d) + "/")]

        for filename in files:
            rel_file_path = os.path.join(rel_root, filename)
            
            # Skip ignored files
            if spec.match_file(rel_file_path):
                continue

            full_path = os.path.join(root, filename)
            
            try:
                # We only want relatively small text files, skip massive binaries
                size = os.path.getsize(full_path)
                if size > 5 * 1024 * 1024:  # Skip files larger than 5MB
                    continue
                    
                _, ext = os.path.splitext(filename)
                language = detect_language(filename)
                
                new_file = File(
                    repository_id=repo.id,
                    file_path=rel_file_path.replace("\\", "/"),
                    extension=ext.lower(),
                    language=language,
                    size_bytes=size
                )
                
                # --- NEW PARSING LOGIC ---
                # We must commit the file first so we have a file.id to link the chunks to
                db.add(new_file)
                db.commit()
                db.refresh(new_file)
                
                chunks_to_insert = []
                
                if language == "Python":
                    with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                        source_code = f.read()
                        
                    parser = PythonCodeParser(source_code)
                    extracted_blocks = parser.parse()
                    
                    for block in extracted_blocks:
                        new_chunk = Chunk(
                            file_id=new_file.id,
                            chunk_type=block["chunk_type"],
                            name=block["name"],
                            content=block["content"],
                            start_line=block["start_line"],
                            end_line=block["end_line"]
                        )
                        chunks_to_insert.append(new_chunk)
                        
                # Bulk insert the chunks for this file
                if chunks_to_insert:
                    db.add_all(chunks_to_insert)
                    db.commit()
                # -----------------------
                
            except Exception as e:
                print(f"Error processing file {rel_file_path}: {e}")

    print(f"Finished processing files for {repo.full_name}")
import ast
from typing import List, Dict, Any

class PythonCodeParser:
    def __init__(self, source_code: str):
        self.source_code = source_code
        self.lines = source_code.splitlines()

    def parse(self) -> List[Dict[str, Any]]:
        """Parses the source code and returns a list of structural chunks."""
        chunks = []
        try:
            tree = ast.parse(self.source_code)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    chunks.append(self._extract_node(node, "class"))
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Only grab top-level functions (methods are grabbed when we walk the class)
                    # For simplicity in this prototype, we'll grab all and rely on name matching
                    chunks.append(self._extract_node(node, "function"))
                    
        except SyntaxError:
            # Fallback for invalid Python code (e.g., Python 2 syntax in a Python 3 parser)
            print("Syntax error while parsing Python file, treating as raw text.")
            return [{"chunk_type": "raw", "name": "raw_block", "content": self.source_code, "start_line": 1, "end_line": len(self.lines)}]
            
        return chunks

    def _extract_node(self, node: ast.AST, chunk_type: str) -> Dict[str, Any]:
        """Extracts the source text and metadata for a specific AST node."""
        start_line = node.lineno
        # node.end_lineno is available in Python 3.8+
        end_line = getattr(node, 'end_lineno', start_line) 
        
        # Reconstruct the code block
        content = "\n".join(self.lines[start_line - 1:end_line])
        
        return {
            "chunk_type": chunk_type,
            "name": getattr(node, "name", "anonymous"),
            "content": content,
            "start_line": start_line,
            "end_line": end_line,
            "metadata_json": {}
        }
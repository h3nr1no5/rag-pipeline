import json
import yaml
from ...core.exceptions import DocumentProcessingError


class OpenAPIParser:
    def parse(self, file_path: str) -> tuple[str, dict]:
        with open(file_path, "r") as f:
            if file_path.endswith(".json"):
                spec = json.load(f)
            else:
                spec = yaml.safe_load(f)
        
        if "openapi" not in spec and "swagger" not in spec:
            raise DocumentProcessingError("Not a valid OpenAPI or Swagger specification")
        
        version = spec.get("openapi") or spec.get("swagger", "Unknown")
        
        info = spec.get("info", {})
        title = info.get("title", "API Documentation")
        description = info.get("description", "")
        
        overview = f"# {title}\n\nVersion: {version}\n\n{description}\n\n"
        
        endpoints = []
        
        paths = spec.get("paths", {})
        for path, methods in paths.items():
            for method, operation in methods.items():
                if method not in ["get", "post", "put", "patch", "delete", "options", "head"]:
                    continue
                
                op_id = operation.get("operationId", f"{method}_{path}")
                summary = operation.get("summary", "")
                description = operation.get("description", "")
                tags = operation.get("tags", [])
                
                params = operation.get("parameters", [])
                request_body = operation.get("requestBody", {})
                responses = operation.get("responses", {})
                
                endpoint_info = {
                    "path": path,
                    "method": method.upper(),
                    "operation_id": op_id,
                    "summary": summary,
                    "description": description,
                    "parameters": params,
                    "request_body": request_body,
                    "responses": responses,
                    "tags": tags,
                }
                endpoints.append(endpoint_info)
                
                endpoint_text = f"""
## {method.upper()} {path}
**Operation ID:** {op_id}
**Summary:** {summary}
**Description:** {description}
**Tags:** {', '.join(tags) if tags else 'None'}

**Parameters:** {len(params)}
**Request Body:** {'Required' if request_body else 'None'}
**Responses:** {', '.join(responses.keys())}
"""
                overview += endpoint_text
        
        return overview, {"endpoints": endpoints, "version": version, "title": title}

    def parse_to_text(self, file_path: str) -> str:
        overview, _ = self.parse(file_path)
        return overview

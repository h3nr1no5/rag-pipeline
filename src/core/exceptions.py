class RAGPipelineError(Exception):
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class AuthenticationError(RAGPipelineError):
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, status_code=401)


class AuthorizationError(RAGPipelineError):
    def __init__(self, message: str = "Not authorized"):
        super().__init__(message, status_code=403)


class NotFoundError(RAGPipelineError):
    def __init__(self, message: str = "Resource not found"):
        super().__init__(message, status_code=404)


class ValidationError(RAGPipelineError):
    def __init__(self, message: str = "Validation failed"):
        super().__init__(message, status_code=400)


class DocumentProcessingError(RAGPipelineError):
    def __init__(self, message: str = "Document processing failed"):
        super().__init__(message, status_code=422)


class EmbeddingError(RAGPipelineError):
    def __init__(self, message: str = "Embedding generation failed"):
        super().__init__(message, status_code=500)


class LLMError(RAGPipelineError):
    def __init__(self, message: str = "LLM inference failed"):
        super().__init__(message, status_code=500)

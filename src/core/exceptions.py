class RAGPipelineException(Exception):
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class AuthenticationError(RAGPipelineException):
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, status_code=401)


class AuthorizationError(RAGPipelineException):
    def __init__(self, message: str = "Not authorized"):
        super().__init__(message, status_code=403)


class NotFoundError(RAGPipelineException):
    def __init__(self, message: str = "Resource not found"):
        super().__init__(message, status_code=404)


class ValidationError(RAGPipelineException):
    def __init__(self, message: str = "Validation failed"):
        super().__init__(message, status_code=400)


class DocumentProcessingError(RAGPipelineException):
    def __init__(self, message: str = "Document processing failed"):
        super().__init__(message, status_code=422)


class EmbeddingError(RAGPipelineException):
    def __init__(self, message: str = "Embedding generation failed"):
        super().__init__(message, status_code=500)


class LLMError(RAGPipelineException):
    def __init__(self, message: str = "LLM inference failed"):
        super().__init__(message, status_code=500)

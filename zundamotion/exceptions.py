from typing import Optional


class ValidationError(Exception):
    """Zundamotionでのバリデーションエラーを表す例外。"""

    def __init__(
        self,
        message: str,
        line_number: Optional[int] = None,
        column_number: Optional[int] = None,
    ):
        super().__init__(message)
        self.message = message
        self.line_number = line_number
        self.column_number = column_number

    def __str__(self):
        if self.line_number is not None:
            return f"Validation Error: {self.message} (Line: {self.line_number}, Column: {self.column_number})"
        return f"Validation Error: {self.message}"


class PipelineError(Exception):
    """パイプライン処理で発生したエラーを表す例外。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def __str__(self):
        return f"Pipeline Error: {self.message}"


class CacheError(Exception):
    """キャッシュ処理に関連するエラーを表す例外。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def __str__(self):
        return f"Cache Error: {self.message}"

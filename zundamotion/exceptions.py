from typing import Optional


class ValidationError(Exception):
    """Custom exception for validation errors in Zundamotion."""

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

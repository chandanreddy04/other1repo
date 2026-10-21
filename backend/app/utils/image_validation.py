"""
Simple image validation utilities.
"""

import io

from fastapi import HTTPException, UploadFile, status
from PIL import Image, UnidentifiedImageError

ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/jpg", "image/webp"]
MAX_FILE_SIZE_MB = 10
MAX_IMAGE_DIMENSION = 4096


async def validate_image(file: UploadFile, max_size_mb: int | None = None) -> bytes:
    """
    Validate image file type and size.

    Args:
        file: The uploaded file
        max_size_mb: Maximum file size in MB (default: 10)

    Returns:
        The file contents as bytes

    Raises:
        HTTPException: If validation fails
    """
    # Check content type
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type not allowed. Allowed types: {', '.join(ALLOWED_IMAGE_TYPES)}",
        )

    # Read file contents
    contents = await file.read()
    await file.seek(0)  # Reset file pointer

    # Check file size
    max_size = (max_size_mb or MAX_FILE_SIZE_MB) * 1024 * 1024
    if len(contents) > max_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File size exceeds {max_size_mb or MAX_FILE_SIZE_MB}MB limit",
        )

    # Validate it's actually an image
    try:
        image = Image.open(io.BytesIO(contents))
        width, height = image.size

        if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Image dimensions exceed {MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION} pixels",
            )
    except UnidentifiedImageError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image file"
        ) from None

    return contents

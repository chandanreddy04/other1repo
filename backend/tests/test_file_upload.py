"""Tests for file_upload.upload_image — dev and prod paths."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
class TestUploadImage:
    @patch("app.services.file_upload.settings")
    @patch("app.services.file_upload.validate_image", new_callable=AsyncMock)
    async def test_dev_saves_locally(self, mock_validate, mock_settings):
        from app.services.file_upload import upload_image

        mock_settings.ENVIRONMENT = "development"
        mock_validate.return_value = b"fake-image-bytes"

        file = MagicMock()
        file.filename = "photo.jpg"
        file.content_type = "image/jpeg"

        with patch("app.services.file_upload._save_locally", new_callable=AsyncMock) as mock_save:
            mock_save.return_value = "/uploads/outfit-photos/uid/ts.jpg"
            url = await upload_image(file, "outfit-photos", uuid4())

        assert url.startswith("/uploads/")
        mock_save.assert_called_once()

    @patch("app.services.file_upload.settings")
    @patch("app.services.file_upload.validate_image", new_callable=AsyncMock)
    async def test_prod_uses_blob_storage(self, mock_validate, mock_settings):
        from app.services.file_upload import upload_image

        mock_settings.ENVIRONMENT = "production"
        mock_validate.return_value = b"fake-image-bytes"

        file = MagicMock()
        file.filename = "photo.png"
        file.content_type = "image/png"

        mock_blob_svc = MagicMock()
        mock_blob_svc.upload_file = AsyncMock(return_value="https://madeithome-photos.s3.us-west-2.amazonaws.com/photos/photo.png")
        with patch("app.services.blob_storage.get_blob_storage_service", return_value=mock_blob_svc):
            url = await upload_image(file, "outfit-photos", uuid4())

        assert url.startswith("https://")

    @patch("app.services.file_upload.settings")
    @patch("app.services.file_upload.validate_image", new_callable=AsyncMock)
    async def test_validation_error_propagates(self, mock_validate, mock_settings):
        from app.services.file_upload import upload_image

        mock_settings.ENVIRONMENT = "development"
        mock_validate.side_effect = HTTPException(status_code=400, detail="Invalid image")

        file = MagicMock()
        file.filename = "bad.txt"

        with pytest.raises(HTTPException) as exc_info:
            await upload_image(file, "outfit-photos", uuid4())
        assert exc_info.value.status_code == 400

    @patch("app.services.file_upload.settings")
    @patch("app.services.file_upload.validate_image", new_callable=AsyncMock)
    async def test_unexpected_error_returns_500(self, mock_validate, mock_settings):
        from app.services.file_upload import upload_image

        mock_settings.ENVIRONMENT = "production"
        mock_validate.return_value = b"bytes"

        file = MagicMock()
        file.filename = "photo.jpg"
        file.content_type = "image/jpeg"

        mock_blob_svc = MagicMock()
        mock_blob_svc.upload_file = AsyncMock(side_effect=RuntimeError("boom"))
        with (
            patch("app.services.blob_storage.get_blob_storage_service", return_value=mock_blob_svc),
            pytest.raises(HTTPException) as exc_info,
        ):
            await upload_image(file, "outfit-photos", uuid4())
        assert exc_info.value.status_code == 500

    @patch("app.services.file_upload.settings")
    @patch("app.services.file_upload.validate_image", new_callable=AsyncMock)
    async def test_no_extension_defaults_to_jpg(self, mock_validate, mock_settings):
        from app.services.file_upload import upload_image

        mock_settings.ENVIRONMENT = "development"
        mock_validate.return_value = b"bytes"

        file = MagicMock()
        file.filename = "noext"
        file.content_type = "image/jpeg"

        with patch("app.services.file_upload._save_locally", new_callable=AsyncMock) as mock_save:
            mock_save.return_value = "/uploads/test.jpg"
            await upload_image(file, "photos", uuid4())

        call_key = mock_save.call_args[0][1]
        assert call_key.endswith(".jpg")

# Photo storage bucket — used by the backend's S3 storage backend
# (services/storage_s3.py) when STORAGE_BACKEND=s3.
#
# Private bucket; the app uploads via the task role's IAM permissions
# (added in PR 9's iam.tf) and serves clients via presigned URLs.

resource "aws_s3_bucket" "photos" {
  bucket = "${local.name_prefix}-photos-${local.env}-${data.aws_caller_identity.current.account_id}"

  # Photos are user data — never destroy this bucket via `terraform
  # destroy`. To intentionally remove an environment, the operator must
  # empty the bucket first, then comment out this lifecycle block.
  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name = "${local.name_prefix}-photos-${local.env}"
  }
}

# Versioning ON — the task role has s3:DeleteObject (used by the cleanup
# loop in session_tasks.py), and versioning is the cheapest defense
# against accidental wipes. Combined with the lifecycle rule below that
# expires noncurrent versions after 30 days, the storage cost stays
# bounded while giving us 30 days of recovery on any deleted photo.
resource "aws_s3_bucket_versioning" "photos" {
  bucket = aws_s3_bucket.photos.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "photos" {
  bucket = aws_s3_bucket.photos.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "photos" {
  bucket                  = aws_s3_bucket.photos.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Clean up failed multipart uploads + expire noncurrent versions so
# versioning doesn't grow unbounded. Versioning is on (above) to recover
# from accidental deletes for up to 30 days.
resource "aws_s3_bucket_lifecycle_configuration" "photos" {
  bucket = aws_s3_bucket.photos.id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    # An empty filter matches all objects; required field on the rule.
    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"
    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  # Background photo discovery was removed on 2026-09-05 (migration
  # d75a707d6ba9 dropped the session_photos table that indexed these keys),
  # so anything still under session-photos/ is an orphan nothing can purge.
  # Expire it so the "deleted 7 days after your session" promise holds for
  # pre-removal uploads too (the delete marker's noncurrent copy ages out via
  # the rule above). A no-op once the prefix is empty.
  rule {
    id     = "expire-orphaned-session-photos"
    status = "Enabled"

    filter {
      prefix = "session-photos/"
    }

    expiration {
      days = 1
    }
  }
}

# CORS — mobile app uploads photos directly via presigned URLs (avoids
# routing photo bytes through the backend). Origin is scoped per env so
# a misconfigured staging build can't upload to the production bucket
# (and vice versa).
# GET is included for the web admin UI fetches; mobile uses native image
# loaders that don't CORS-preflight, so they wouldn't need it.
resource "aws_s3_bucket_cors_configuration" "photos" {
  bucket = aws_s3_bucket.photos.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "PUT"]
    allowed_origins = var.environment_name == "production" ? [
      "https://app.madeithomeapp.com",
      ] : [
      "https://staging-app.madeithomeapp.com",
    ]
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

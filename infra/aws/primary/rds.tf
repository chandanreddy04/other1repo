# RDS Postgres — the app's primary database.
#
# Sized at 2 vCPU / 4 GB / 32 GB storage (single-AZ, no HA) for cost
# parity. Lives in private subnets across both
# AZs (RDS subnet groups require ≥2 even when the instance is single-AZ
# so a future failover-to-multi-AZ doesn't require re-creating it).
#
# Admin credentials: managed by AWS via `manage_master_user_password = true`,
# which has RDS create + rotate the Secrets Manager secret itself. No
# plaintext password ever sits in Terraform state. init-db.sh (PR 13)
# reads from the auto-created secret to create the least-priv app role;
# the app's DATABASE_URL then uses the app role, never the admin.

# --- Subnet group --------------------------------------------------------
resource "aws_db_subnet_group" "main" {
  name       = "${local.name_prefix}-db-${local.env}"
  subnet_ids = aws_subnet.private[*].id

  tags = {
    Name = "${local.name_prefix}-db-subnets-${local.env}"
  }
}

# --- Security group ------------------------------------------------------
# Created here with no inbound rules. The task SG (PR 9/10) will add an
# `aws_security_group_rule` granting itself ingress on 5432 — avoids a
# circular dependency between the two SGs.
resource "aws_security_group" "rds" {
  name        = "${local.name_prefix}-rds-${local.env}"
  description = "RDS Postgres access - inbound rules added by sibling resources"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-rds-${local.env}"
  }
}

# --- Parameter group -----------------------------------------------------
# Family `postgres16` matches the engine_version below; keep them in sync.
# `name_prefix` + create_before_destroy lets us swap the group in place when
# a parameter changes — otherwise the delete-then-create order fails
# because the original is still attached to the DB instance.
resource "aws_db_parameter_group" "main" {
  name_prefix = "${local.name_prefix}-pg16-${local.env}-"
  family      = "postgres16"
  description = "Postgres 16 parameter overrides for made-it-home"

  # Force TLS on all connections — the app enforces this via
  # DB_SSL_REQUIRE=true, but Postgres can also enforce it server-side.
  # apply_method pinned to match how it's applied in prod (the value is
  # already active; this only silences a no-op provider-default diff).
  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "pending-reboot"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# --- Instance ------------------------------------------------------------
resource "aws_db_instance" "main" {
  identifier = "${local.name_prefix}-db-${local.env}"
  engine     = "postgres"
  # Create-time floor only: a FRESH bootstrap gets the latest 16.x. After
  # creation AWS owns the live minor version (auto_minor_version_upgrade, RDS
  # default), and `ignore_changes = [engine_version]` below keeps plans clean —
  # without it, auto-upgraded minors (16.13 → 16.x) make every later apply try
  # an impossible Postgres downgrade back to this value and error.
  # MAJOR upgrade procedure (rare, deliberate): temporarily drop engine_version
  # from ignore_changes, set it to the new major + allow_major_version_upgrade,
  # apply, then restore the ignore. See docs/deployment.md.
  engine_version = "16"
  instance_class = "db.t4g.medium"

  allocated_storage     = 32
  storage_type          = "gp3"
  storage_encrypted     = true
  max_allocated_storage = 100 # autoscale headroom; only pay for what's used

  db_name  = "madeithome"
  username = "mihadmin"
  # `manage_master_user_password = true` has RDS generate the password and
  # store it in a Secrets Manager secret that AWS rotates. No plaintext in
  # Terraform state, no manual random_password resource.
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  parameter_group_name   = aws_db_parameter_group.main.name
  publicly_accessible    = false
  port                   = 5432

  # Multi-AZ in PRODUCTION only (automatic ~1-2 min in-region failover,
  # zero RPO — covers the common host/AZ failure that dominates the
  # downtime budget). Staging stays single-AZ to keep costs down; its
  # downtime tolerance is high. Cross-region disaster recovery is handled
  # NOT by a warm-standby stack but by backup-only DR: production
  # automated backups are replicated to the failover region (see
  # rds_backup_replication.tf) and recovered per docs/dr-runbook-aws.md.
  # Times are UTC: backup runs 01:00-02:00 PT, maintenance 02:00-03:00 PT
  # Sunday — both off-peak for the US-centric safety app.
  multi_az                = local.is_production
  backup_retention_period = 30
  backup_window           = "08:00-09:00"
  maintenance_window      = "Sun:09:00-Sun:10:00"

  # Snapshot on destroy — irreversibly losing prod data without one is a
  # disaster scenario. Staging can override via -var if needed.
  # `timestamp()` is evaluated at plan time and captured into state on
  # first apply; ignore_changes below keeps later plans from drifting
  # against the original creation time.
  skip_final_snapshot       = false
  final_snapshot_identifier = "${local.name_prefix}-db-${local.env}-final-${formatdate("YYYYMMDDhhmmss", timestamp())}"
  deletion_protection       = true

  # Performance Insights and enhanced monitoring add cost; defer until
  # we have load to investigate.
  performance_insights_enabled = false

  tags = {
    Name = "${local.name_prefix}-db-${local.env}"
  }

  lifecycle {
    ignore_changes = [
      # Captured at create time; timestamp() re-evaluates every plan otherwise.
      final_snapshot_identifier,
      # AWS owns the live minor version (auto_minor_version_upgrade). Ignoring
      # it keeps plans clean instead of trying to downgrade to the create-time
      # floor. Major upgrades: see the engine_version note above.
      engine_version,
    ]
  }
}

# Cross-region automated backup replication — PRODUCTION only.
#
# WHY THIS EXISTS: RDS automated backups (and PITR) are REGIONAL. If
# us-west-2 is lost, the backups are lost with it — so "we can restore
# from backup in another region" is FALSE without this. This resource
# continuously replicates production's automated backups to the failover
# region (us-east-2), giving a region-loss recovery path from backup with
# point-in-time-recovery preserved.
#
# This is deliberately BACKUP-ONLY DR: no standby compute, no read
# replica, no automatic failover. Recovery is a manual, runbook-driven
# restore — see docs/dr-runbook-aws.md. It is the low-cost middle ground
# between "regional backups only" (no region-loss protection) and the full
# warm-standby failover/ stack (more cost + complexity than this app wants
# today).
#
# COST: backup storage in us-east-2 + cross-region transfer of backup
# data. No compute. Small for a 32 GB, low-write database.

# Encrypted source databases require a KMS key IN THE DESTINATION REGION
# for the replicated backups — the source's default aws/rds key can't be
# used cross-region. A customer-managed key in us-east-2 satisfies this.
resource "aws_kms_key" "backup_dr" {
  count                   = local.is_production ? 1 : 0
  provider                = aws.failover
  description             = "CMK for cross-region replicated RDS automated backups (${local.name_prefix}-db-${local.env})"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = {
    Name = "${local.name_prefix}-backup-dr-${local.env}"
  }
}

resource "aws_kms_alias" "backup_dr" {
  count         = local.is_production ? 1 : 0
  provider      = aws.failover
  name          = "alias/${local.name_prefix}-backup-dr-${local.env}"
  target_key_id = aws_kms_key.backup_dr[0].key_id
}

# The replication resource is created in the DESTINATION region (hence the
# aws.failover provider) but points at the source instance's ARN in the
# primary region. Retention mirrors the source so the cross-region copy
# keeps the same window.
resource "aws_db_instance_automated_backups_replication" "main" {
  count                  = local.is_production ? 1 : 0
  provider               = aws.failover
  source_db_instance_arn = aws_db_instance.main.arn
  retention_period       = aws_db_instance.main.backup_retention_period
  kms_key_id             = aws_kms_key.backup_dr[0].arn
}

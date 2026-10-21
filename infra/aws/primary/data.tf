# Shared data sources used across the stack. Pulled out here so referrers
# (variables.tf, vpc.tf, future *.tf) don't depend on a sibling file's
# implementation order.

# Used to suffix globally-unique resource names (S3 buckets) with the
# account ID — see infra/aws/README.md naming convention.
data "aws_caller_identity" "current" {}

# Lists AZs in the active region. The list is sorted by name and stable
# per-account-per-region (us-west-2a in this account always maps to the
# same physical AZ). Stable across applies — we slice the first two to
# get a deterministic subnet→AZ mapping.
#
# Caveat: us-west-2a in account A is NOT necessarily the same physical AZ
# as us-west-2a in account B. Not relevant unless we ever cross-account
# share infrastructure.
data "aws_availability_zones" "available" {
  state = "available"
}

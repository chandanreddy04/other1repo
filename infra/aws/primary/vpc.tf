# VPC + subnets + IGW + route tables.
#
# Subnet model (matches the decision made during planning):
#   - Public subnets host the ALB AND the Fargate tasks (assign_public_ip=true
#     with tight security groups). Saves ~$35/mo per AZ in NAT Gateway costs
#     vs. private-subnet-only Fargate. Inbound is still gated by SGs.
#   - Private subnets host RDS only. RDS doesn't need outbound; no NAT.
#
# Security stance: tasks have public IPs but their SG only allows inbound
# from the ALB's SG. See PR 10 (alb.tf + ecs_web.tf) for the SG wiring.

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true # required for RDS private DNS

  tags = {
    Name = "${local.name_prefix}-vpc-${local.env}"
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-igw-${local.env}"
  }
}

# --- Public subnets ------------------------------------------------------
resource "aws_subnet" "public" {
  count             = length(var.public_subnet_cidrs)
  vpc_id            = aws_vpc.main.id
  cidr_block        = var.public_subnet_cidrs[count.index]
  availability_zone = local.azs[count.index]
  # Subnet-level default is off. The ECS service network_configuration sets
  # assign_public_ip per-task (PR 10), which overrides this either way. Off
  # at the subnet level means anything launched here without explicit
  # config (e.g., manual debug instances) won't accidentally get a public IP.
  map_public_ip_on_launch = false

  tags = {
    # AZ embedded in the name to match the subnet→AZ binding visually in the
    # console. AZ names are stable per-account-per-region (us-west-2a here
    # always means the same physical AZ for this account).
    Name = "${local.name_prefix}-public-${local.env}-${local.azs[count.index]}"
    Tier = "public"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${local.name_prefix}-rt-public-${local.env}"
  }
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# --- Private subnets -----------------------------------------------------
# No outbound route (no NAT). RDS in here doesn't need it; the moment any
# resource that DOES need outbound lands in a private subnet, add a NAT
# Gateway and a default route here.
resource "aws_subnet" "private" {
  count             = length(var.private_subnet_cidrs)
  vpc_id            = aws_vpc.main.id
  cidr_block        = var.private_subnet_cidrs[count.index]
  availability_zone = local.azs[count.index]

  tags = {
    Name = "${local.name_prefix}-private-${local.env}-${local.azs[count.index]}"
    Tier = "private"
  }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  # No explicit routes. AWS auto-creates an implicit `local` route covering
  # the VPC CIDR (10.20.0.0/16), which is all RDS needs. Add explicit
  # routes here for VPC peering, transit gateway, or VPN attachments.

  tags = {
    Name = "${local.name_prefix}-rt-private-${local.env}"
  }
}

resource "aws_route_table_association" "private" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

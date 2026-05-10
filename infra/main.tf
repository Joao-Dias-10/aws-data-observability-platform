terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }

  backend "s3" {
    bucket = "tfstate-sla-data-platform-dev-jpd"   # atualize para o seu bucket de estado
    key    = "sla-platform/terraform.tfstate"
    region = "us-east-1"
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "sla-platform"
      Environment = var.environment
      ManagedBy   = "terraform"
      Owner       = "data-engineering"
    }
  }
}

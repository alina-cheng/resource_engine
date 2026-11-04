terraform {
  required_version = ">= 1.6"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.60" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
  backend "s3" {}   # configured by `terraform init -backend-config=...` (see docs/deployment.md)
}

provider "aws" {
  region = var.region
  default_tags { tags = { Project = var.project, ManagedBy = "terraform" } }
}

variable "project"          { default = "resource-engine" }
variable "region"           { default = "us-west-2" }
variable "image_tag"        { default = "bootstrap" }
variable "app_count"        { default = 1 }
variable "app_cpu"          { default = 512 }
variable "app_memory"       { default = 1024 }
variable "db_min_acu"       { default = 0.5 }
variable "db_max_acu"       { default = 4 }
variable "db_engine_version" { default = "16.4" }
variable "certificate_arn"  {
  description = "ACM certificate for HTTPS. Empty = HTTP only (demo)."
  default     = ""
}
variable "bedrock_model_id" { default = "anthropic.claude-3-5-haiku-20241022-v1:0" }
variable "llm_backend"      { default = "bedrock" }
variable "website_backend"  { default = "live" }
variable "enable_opensearch" { default = false }
variable "import_schedule"      { default = "cron(0 11 * * ? *)" }   # 04:00 Pacific, daily
variable "maintenance_schedule" { default = "cron(0 12 * * ? *)" }   # after the import
variable "maintenance_batch"    { default = 200 }

locals {
  name = var.project
  azs  = slice(data.aws_availability_zones.this.names, 0, 2)
}
data "aws_availability_zones" "this" { state = "available" }
data "aws_caller_identity" "me" {}

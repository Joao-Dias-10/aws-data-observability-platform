variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment deve ser dev, staging ou prod."
  }
}

variable "project" {
  type    = string
  default = "sla-platform"
}

variable "alert_email" {
  description = "Email para receber alertas via SNS"
  type        = string
}

variable "slack_webhook_url" {
  description = "Slack Incoming Webhook URL (opcional — deixe vazio para só logar)"
  type        = string
  default     = ""
  sensitive   = true
}

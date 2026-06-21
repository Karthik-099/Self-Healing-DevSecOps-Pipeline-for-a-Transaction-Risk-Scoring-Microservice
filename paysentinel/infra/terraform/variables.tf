variable "aws_region" {
  default = "us-east-1"
}

variable "cluster_name" {
  default = "paysentinel"
}

variable "node_instance_type" {
  default = "t3.medium"
}

variable "desired_nodes" {
  default = 2
}

variable "dockerhub_username" {
  description = "Docker Hub username for image pulls"
}

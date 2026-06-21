resource "aws_ecr_repository" "paysentinel" {
  name                 = "paysentinel"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  lifecycle_policy {
  }
}

resource "aws_ecr_lifecycle_policy" "paysentinel" {
  repository = aws_ecr_repository.paysentinel.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

output "ecr_repository_url" {
  value = aws_ecr_repository.paysentinel.repository_url
}

data "aws_iam_openid_connect_provider" "eks" {
  url = module.eks.cluster_oidc_issuer_url
}

data "aws_iam_policy_document" "paysentinel_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.eks.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${replace(data.aws_iam_openid_connect_provider.eks.url, "https://", "")}:sub"
      values   = ["system:serviceaccount:paysentinel:paysentinel-sa"]
    }
  }
}

resource "aws_iam_role" "paysentinel" {
  name               = "paysentinel-irsa"
  assume_role_policy = data.aws_iam_policy_document.paysentinel_assume.json
}

resource "aws_iam_role_policy" "paysentinel_ecr" {
  name = "paysentinel-ecr-readonly"
  role = aws_iam_role.paysentinel.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "ecr:GetAuthorizationToken"]
      Resource = "*"
    }]
  })
}

output "irsa_role_arn" {
  value = aws_iam_role.paysentinel.arn
}

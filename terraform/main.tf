provider "aws" {
  region = "us-west-2"  # Change to your desired region
}

resource "aws_iam_role" "lambda_role" {
  name = "lambda_role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action    = "sts:AssumeRole",
        Effect    = "Allow",
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      },
    ],
  })
}

resource "aws_iam_policy_attachment" "lambda_policy" {
  name       = "lambda_policy_attachment"
  roles      = [aws_iam_role.lambda_role.name]
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" # Basic logging permissions
}

resource "aws_lambda_function" "find_campsites_lambda" {
  function_name = "find_campsites_lambda"
  filename      = "lambda_function.zip"  # Path to your packaged Lambda zip
  source_code_hash = filebase64sha256("lambda_function.zip")
  handler       = "app.lambda_handler"  # Change this based on your function entry point
  runtime       = "python3.9"  # Adjust runtime if different

  role = aws_iam_role.lambda_role.arn

  environment {
    variables = {
      # Add any environment variables here if needed
    }
  }

  # Optional: Memory and timeout settings
  memory_size      = 128
  timeout          = 30
}

resource "aws_api_gateway_rest_api" "api" {
  name        = "FindCampsitesAPI"
  description = "API Gateway for find campsites Lambda function"
}

resource "aws_api_gateway_resource" "lambda_resource" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "find-campsites"
}

resource "aws_api_gateway_method" "lambda_method" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  resource_id   = aws_api_gateway_resource.lambda_resource.id
  http_method   = "POST"
  authorization = "NONE"
}

resource "aws_lambda_permission" "apigw_lambda" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.find_campsites_lambda.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api.execution_arn}/*/POST/find-campsites"
}

resource "aws_api_gateway_integration" "lambda_integration" {
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id             = aws_api_gateway_resource.lambda_resource.id
  http_method             = aws_api_gateway_method.lambda_method.http_method
  integration_http_method = "POST"  # Should be POST for AWS_PROXY integration
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.find_campsites_lambda.invoke_arn
}

resource "aws_api_gateway_deployment" "lambda_deployment" {
  depends_on  = [aws_api_gateway_integration.lambda_integration]
  rest_api_id = aws_api_gateway_rest_api.api.id
  stage_name  = "prod"
}

output "api_url" {
  value = "https://${aws_api_gateway_rest_api.api.id}.execute-api.us-west-2.amazonaws.com/prod/find-campsites"
}

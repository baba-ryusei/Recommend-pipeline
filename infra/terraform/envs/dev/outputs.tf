output "buckets" {
  value = { for k, b in google_storage_bucket.this : k => b.url }
}

output "datasets" {
  value = [for d in google_bigquery_dataset.this : d.dataset_id]
}

output "service_accounts" {
  value = { for k, sa in google_service_account.this : k => sa.email }
}

output "docker_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker.repository_id}"
}

output "kfp_repository" {
  value = "https://${var.region}-kfp.pkg.dev/${var.project_id}/${google_artifact_registry_repository.kfp.repository_id}"
}

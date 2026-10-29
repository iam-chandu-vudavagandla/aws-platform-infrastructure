package main

import rego.v1

secure_application_workload := {
	"apiVersion": "apps/v1",
	"kind": "Deployment",
	"metadata": {
		"name": "aws-platform-app",
		"namespace": "dev",
	},
	"spec": {
		"template": {
			"metadata": {
				"labels": {
					"app": "aws-platform-app",
				},
			},
			"spec": {
				"securityContext": {
					"runAsNonRoot": true,
					"seccompProfile": {
						"type": "RuntimeDefault",
					},
				},
				"containers": [
					{
						"name": "app",
						"image": concat(
							"",
							[
								"example/app@sha256:",
								"00000000000000000000000000000000",
								"00000000000000000000000000000000",
							],
						),
						"resources": {
							"requests": {
								"cpu": "50m",
								"memory": "64Mi",
							},
							"limits": {
								"cpu": "200m",
								"memory": "128Mi",
							},
						},
						"livenessProbe": {
							"httpGet": {
								"path": "/health",
								"port": 8080,
							},
						},
						"readinessProbe": {
							"httpGet": {
								"path": "/ready",
								"port": 8080,
							},
						},
						"securityContext": {
							"allowPrivilegeEscalation": false,
							"privileged": false,
							"readOnlyRootFilesystem": true,
						},
					},
				],
			},
		},
	},
}

privileged_workload := json.patch(
	secure_application_workload,
	[
		{
			"op": "replace",
			"path": concat(
				"",
				[
					"/spec/template/spec/containers/0/",
					"securityContext/privileged",
				],
			),
			"value": true,
		},
	],
)

unpinned_development_workload := json.patch(
	secure_application_workload,
	[
		{
			"op": "replace",
			"path": "/spec/template/spec/containers/0/image",
			"value": "example/app:1.0",
		},
	],
)

test_secure_application_workload_is_allowed if {
	violations := deny with input as secure_application_workload
	count(violations) == 0
}

test_privileged_container_is_denied if {
	violations := deny with input as privileged_workload
	some message in violations
	contains(message, "must not be privileged")
}

test_unpinned_development_image_is_denied if {
	violations := deny with input as unpinned_development_workload
	some message in violations
	contains(message, "must use a digest-pinned image")
}

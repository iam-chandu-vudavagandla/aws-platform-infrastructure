package main

import rego.v1

workload_kinds := {
	"DaemonSet",
	"Deployment",
	"StatefulSet",
}

required_resources := [
	{"section": "requests", "name": "cpu"},
	{"section": "requests", "name": "memory"},
	{"section": "limits", "name": "cpu"},
	{"section": "limits", "name": "memory"},
]

required_probes := [
	"livenessProbe",
	"readinessProbe",
]

is_workload if {
	input.kind in workload_kinds
}

pod_spec := input.spec.template.spec if {
	is_workload
}

is_application_workload if {
	is_workload
	input.spec.template.metadata.labels.app == "aws-platform-app"
}

deny contains message if {
	is_workload
	container := pod_spec.containers[_]
	security_context := object.get(
		container,
		"securityContext",
		{},
	)
	object.get(
		security_context,
		"privileged",
		false,
	) == true

	message := sprintf(
		"%s %s container %s must not be privileged",
		[
			input.kind,
			input.metadata.name,
			container.name,
		],
	)
}

deny contains message if {
	is_workload
	container := pod_spec.containers[_]
	requirement := required_resources[_]
	resources := object.get(container, "resources", {})
	values := object.get(
		resources,
		requirement.section,
		{},
	)
	object.get(
		values,
		requirement.name,
		"",
	) == ""

	message := sprintf(
		"%s %s container %s must define %s.%s",
		[
			input.kind,
			input.metadata.name,
			container.name,
			requirement.section,
			requirement.name,
		],
	)
}

deny contains message if {
	is_workload
	container := pod_spec.containers[_]
	probe := required_probes[_]
	object.get(container, probe, null) == null

	message := sprintf(
		"%s %s container %s must define %s",
		[
			input.kind,
			input.metadata.name,
			container.name,
			probe,
		],
	)
}

deny contains message if {
	is_application_workload
	pod_security_context := object.get(
		pod_spec,
		"securityContext",
		{},
	)
	object.get(
		pod_security_context,
		"runAsNonRoot",
		false,
	) != true

	message := sprintf(
		"%s %s must set pod securityContext.runAsNonRoot",
		[input.kind, input.metadata.name],
	)
}

deny contains message if {
	is_application_workload
	container := pod_spec.containers[_]
	security_context := object.get(
		container,
		"securityContext",
		{},
	)
	object.get(
		security_context,
		"allowPrivilegeEscalation",
		true,
	) != false

	message := sprintf(
		"%s %s container %s must disable allowPrivilegeEscalation",
		[input.kind, input.metadata.name, container.name],
	)
}

deny contains message if {
	is_application_workload
	container := pod_spec.containers[_]
	security_context := object.get(
		container,
		"securityContext",
		{},
	)
	object.get(
		security_context,
		"readOnlyRootFilesystem",
		false,
	) != true

	message := sprintf(
		"%s %s container %s must use a read-only root filesystem",
		[input.kind, input.metadata.name, container.name],
	)
}

deny contains message if {
	is_application_workload
	pod_security_context := object.get(
		pod_spec,
		"securityContext",
		{},
	)
	seccomp_profile := object.get(
		pod_security_context,
		"seccompProfile",
		{},
	)
	object.get(
		seccomp_profile,
		"type",
		"",
	) != "RuntimeDefault"

	message := sprintf(
		"%s %s must use the RuntimeDefault seccomp profile",
		[input.kind, input.metadata.name],
	)
}

deny contains message if {
	input.kind == "Deployment"
	input.metadata.namespace == "dev"
	container := input.spec.template.spec.containers[_]
	not contains(container.image, "@sha256:")

	message := sprintf(
		"Deployment %s container %s must use a digest-pinned image",
		[input.metadata.name, container.name],
	)
}

deny contains message if {
	is_workload
	input.metadata.namespace != "dev"
	container := pod_spec.containers[_]
	endswith(container.image, ":latest")

	message := sprintf(
		"%s %s container %s must not use the latest tag",
		[input.kind, input.metadata.name, container.name],
	)
}

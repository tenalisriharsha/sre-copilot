{{- define "sre-copilot.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "sre-copilot.fullname" -}}
{{- .Release.Name -}}-{{- .Chart.Name -}}
{{- end -}}

{{- define "sre-copilot.labels" -}}
app.kubernetes.io/name: {{ include "sre-copilot.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "sre-copilot.selectorLabels" -}}
app.kubernetes.io/name: {{ include "sre-copilot.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "sre-copilot.secretName" -}}
{{- if .Values.secret.existingSecret -}}
{{- .Values.secret.existingSecret -}}
{{- else -}}
{{- include "sre-copilot.fullname" . -}}
{{- end -}}
{{- end -}}

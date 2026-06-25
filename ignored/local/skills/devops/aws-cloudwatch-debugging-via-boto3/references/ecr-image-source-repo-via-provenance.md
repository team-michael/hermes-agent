# ECR Image Source Repo via Provenance

Use this when:
- you have an ECS task definition or ECR image tag
- you need to find the source repository/branch/workflow that built it
- the repo is private or not present on disk
- you only have AWS read access

## Why this matters

Modern ECR images may include OCI attestation manifests with SLSA provenance.
These often reveal:
- GitHub repository (`team/repo`)
- workflow file
- branch/ref
- actor
- build inputs

This is often enough to identify the real source repo even when:
- `git clone` is impossible
- public GitHub search finds nothing
- task definitions only show image tags

## Workflow

1. **Start from ECS task definition or image tag**
   - `ecs.describe_task_definition()`
   - extract image like:
     - `702197142747.dkr.ecr.ap-northeast-2.amazonaws.com/segment-publisher:segment-publisher-<sha>`

2. **Get the ECR image index/manifest**
   - use `ecr.batch_get_image()`
   - if the first manifest is an OCI image index, select the linux/amd64 image manifest digest and fetch that too

3. **Inspect attestation manifest(s)**
   - OCI indexes may include a second manifest annotated as:
     - `vnd.docker.reference.type = attestation-manifest`
   - fetch that manifest digest with `batch_get_image()`
   - its layer may have media type `application/vnd.in-toto+json`

4. **Download the attestation layer**
   - use `ecr.get_download_url_for_layer()` on the in-toto layer digest
   - parse the JSON payload

5. **Extract repository metadata**
   - look in:
     - `predicate.buildDefinition.internalParameters.github_repository`
     - `predicate.buildDefinition.internalParameters.github_ref`
     - `predicate.buildDefinition.internalParameters.github_workflow`
     - `predicate.buildDefinition.github_event_payload.repository.full_name`
   - also inspect `subject[]` image names and tags

6. **State the source clearly**
   - example conclusion:
     - image `segment-publisher:<tag>` was built from GitHub repo `team-michael/notifly-event`
     - workflow `.github/workflows/ecs_build.yml`
     - ref `refs/heads/main`

## Python via terminal pattern

```bash
python - <<'PY'
import boto3, os, json, urllib.request
session = boto3.Session(
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
    aws_session_token=os.environ.get('AWS_SESSION_TOKEN'),
    region_name=os.environ.get('AWS_DEFAULT_REGION', 'ap-northeast-2'),
)
ecr = session.client('ecr')

repo = 'segment-publisher'
tag = 'segment-publisher-<tag>'

resp = ecr.batch_get_image(
    registryId='702197142747',
    repositoryName=repo,
    imageIds=[{'imageTag': tag}],
    acceptedMediaTypes=['application/vnd.oci.image.index.v1+json']
)
index_manifest = json.loads(resp['images'][0]['imageManifest'])
attestation_digest = next(
    m['digest'] for m in index_manifest['manifests']
    if m.get('annotations', {}).get('vnd.docker.reference.type') == 'attestation-manifest'
)

resp = ecr.batch_get_image(
    registryId='702197142747',
    repositoryName=repo,
    imageIds=[{'imageDigest': attestation_digest}],
    acceptedMediaTypes=['application/vnd.oci.image.manifest.v1+json']
)
att_manifest = json.loads(resp['images'][0]['imageManifest'])
layer_digest = att_manifest['layers'][0]['digest']
url = ecr.get_download_url_for_layer(
    registryId='702197142747',
    repositoryName=repo,
    layerDigest=layer_digest,
)['downloadUrl']
with urllib.request.urlopen(url, timeout=30) as r:
    provenance = json.load(r)
print(json.dumps({
    'github_repository': provenance['predicate']['buildDefinition']['internalParameters'].get('github_repository'),
    'github_ref': provenance['predicate']['buildDefinition']['internalParameters'].get('github_ref'),
    'github_workflow': provenance['predicate']['buildDefinition']['internalParameters'].get('github_workflow'),
}, indent=2))
PY
```

## Learned example

For Notifly ECS images, the ECR attestation revealed:
- source repo: `team-michael/notifly-event`
- workflow: `.github/workflows/ecs_build.yml`
- branch: `refs/heads/main`

This was crucial because the repo was private and the available GitHub token authenticated as another user without access, so provenance was the only reliable way to identify the correct source repository.

## Pitfalls

- `batch_get_image()` may first return an OCI index, not the final image manifest.
- The attestation manifest is separate from the runnable image manifest.
- Public GitHub search may miss the repo entirely if it is private.
- Having a valid GitHub token does not imply access to the source repo; provenance can still identify it.

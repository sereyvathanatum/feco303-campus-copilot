# Thunder Client collection

Raw HTTP requests for every external service the copilot uses: NIM chat, NIM
embeddings (`passage` and `query`), the NIM model list, the Laya reference call
against a local `laya-serve` (docs/laya_primer.md), and the four public APIs.

Keys are read from process environment variables through
`{{process.env.NVIDIA_API_KEY}}` and `{{process.env.LAYA_API_KEY}}`. Laya itself needs
no key: the header matters only when `laya-serve` runs behind a bearer token, and
`layaBase` points at `http://127.0.0.1:8000/v1`. No key is ever saved in these files;
the secret scan rejects a commit that contains one.

Open the folder with the Thunder Client extension (git-sync mode), select the
`campus-copilot` environment, and send any request.

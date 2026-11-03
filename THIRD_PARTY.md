# Third-party components and models

The root Apache-2.0 license covers project-authored code. It does not relicense
third-party software, fonts, model weights, datasets, trademarks or websites.

| Component | Source / license | Distribution here |
| --- | --- | --- |
| Laya / laya-browser | [Laya](https://huggingface.co/convaiinnovations/laya), [browser checkpoint](https://huggingface.co/cklxx/laya-browser), Apache-2.0 per upstream | Manifests only; pinned wrapper/weights downloaded during setup |
| Qwen3.5-4B MTP GGUF | [Unsloth model card](https://huggingface.co/unsloth/Qwen3.5-4B-MTP-GGUF), Apache-2.0 per publisher | Manifest only; selected GGUF downloaded separately |
| llama.cpp | [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp), MIT | Build recipe; pinned source downloaded separately with its license |
| Excalidraw | [excalidraw/excalidraw](https://github.com/excalidraw/excalidraw), MIT | Built JS/fonts with EXCALIDRAW-LICENSE.txt and THIRD-PARTY-NOTICES.txt |
| React and frontend dependencies | npm package-lock.json and bundled notices | Compiled frontend assets; per-package notices retained |
| PyTorch / CUDA-linked wheel | [PyTorch](https://github.com/pytorch/pytorch), upstream BSD-style and bundled third-party licenses; [Seeed wheel source](https://github.com/Seeed-Projects/reComputer-Jetson-for-Beginners/tree/main/3-Basic-Tools-and-Getting-Started/3.5-Pytorch) | No wheel redistribution; installer downloads from the publisher source |
| Playwright / Chromium | [Playwright](https://github.com/microsoft/playwright), Apache-2.0; [Chromium](https://www.chromium.org/developers/how-tos/get-the-code/), BSD-style and third-party notices | Installed separately; not committed |

Bundled frontend notices are in
`src/jetson_browser/static/whiteboard/THIRD-PARTY-NOTICES.txt`; font-specific notices
also remain in the local fonts directory. They are generated from the locked build.
Model training dataset licenses are governed upstream; no training dataset is
redistributed. Trip.com content, prices and access rules remain the website's.

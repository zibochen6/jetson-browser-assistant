import json
import time
import torch
from pathlib import Path

assert torch.cuda.is_available(), 'CUDA unavailable; no CPU fallback'
t = time.perf_counter()
a = torch.randn(512, 512, device='cuda')
b = a @ a.T
torch.cuda.synchronize()
result = {'torch': torch.__version__, 'cuda': torch.version.cuda, 'cudnn': torch.backends.cudnn.version(),
          'device': torch.cuda.get_device_name(0), 'capability': torch.cuda.get_device_capability(),
          'finite': bool(torch.isfinite(b).all()), 'seconds': time.perf_counter() - t}
Path('evidence').mkdir(exist_ok=True)
Path('evidence/cuda-check.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))

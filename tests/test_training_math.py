import math
import pytest

torch = pytest.importorskip("torch")
from skillforge.training import completion_logps, preference_loss


def test_tail_projection_matches_full_causal_loss_and_gradients():
    from types import SimpleNamespace
    torch.manual_seed(42)
    class TinyModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.embedding = torch.nn.Embedding(19, 7)
            self.projection = torch.nn.Linear(7, 19)
        def forward(self, input_ids, attention_mask, logits_to_keep, use_cache=False):
            states = self.embedding(input_ids)
            return SimpleNamespace(logits=self.projection(states[:, -logits_to_keep:]))
    model = TinyModel()
    batch = {"input_ids": torch.tensor([[2, 3, 4, 5, 6, 7]]), "attention_mask": torch.ones(1, 6, dtype=torch.long),
        "labels": torch.tensor([[-100, -100, -100, 5, 6, 7]])}
    sums, counts = completion_logps(model, batch)
    loss = -(sums / counts).mean()
    loss.backward()
    tail_grads = [p.grad.clone() for p in model.parameters()]
    model.zero_grad()
    full = model(**{k: batch[k] for k in ["input_ids", "attention_mask"]}, logits_to_keep=6).logits
    expected = torch.nn.functional.cross_entropy(full[:, :-1].reshape(-1, 19), batch["labels"][:, 1:].reshape(-1), ignore_index=-100)
    expected.backward()
    assert torch.allclose(loss, expected, atol=1e-6)
    for actual, parameter in zip(tail_grads, model.parameters()):
        assert torch.allclose(actual, parameter.grad, atol=1e-6)


def test_dpo_reference_initialization_and_preference_gradient():
    chosen = torch.tensor([-3.0], requires_grad=True)
    rejected = torch.tensor([-4.0], requires_grad=True)
    reference_chosen, reference_rejected = chosen.detach(), rejected.detach()
    loss = preference_loss(chosen, rejected, reference_chosen, reference_rejected, 0.1)
    assert loss.item() == pytest.approx(math.log(2), abs=1e-6)
    loss.backward()
    assert chosen.grad.item() < 0 < rejected.grad.item()
    improved = preference_loss(chosen.detach() + 1, rejected.detach(), reference_chosen, reference_rejected, 0.1)
    assert improved < loss


@pytest.mark.skipif(not torch.cuda.is_available(), reason="requires CUDA cuDNN attention")
def test_cudnn_attention_matches_math_forward_and_gradients():
    from torch.nn.attention import SDPBackend, sdpa_kernel
    torch.manual_seed(42)
    q = torch.randn(1, 32, 64, 128, device="cuda", dtype=torch.bfloat16, requires_grad=True)
    k = torch.randn(1, 8, 64, 128, device="cuda", dtype=torch.bfloat16, requires_grad=True)
    v = torch.randn_like(k, requires_grad=True)
    results = []
    for backend in (SDPBackend.MATH, SDPBackend.CUDNN_ATTENTION):
        with sdpa_kernel(backend):
            out = torch.nn.functional.scaled_dot_product_attention(q, k, v, is_causal=True, enable_gqa=True)
            gradients = torch.autograd.grad(out.float().square().mean(), (q, k, v))
            results.append((out.detach(), gradients))
    torch.testing.assert_close(results[0][0], results[1][0], rtol=0.03, atol=0.015)
    for reference, actual in zip(results[0][1], results[1][1]):
        torch.testing.assert_close(reference, actual, rtol=0.04, atol=0.00001)

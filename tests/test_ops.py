import numpy as np
from froog.tensor import Tensor, GPU
import torch
import unittest
import timeit
import functools

def helper_test_op(shape, torch_func, froog_func, atol=1e-7, grad_atol=1e-7, gpu=False, forward_only=False):
  torch_tensors = [torch.rand(x, requires_grad=True) for x in shape]
  froog_tensors = [Tensor(x.detach().numpy()) for x in torch_tensors]

  if gpu:
    froog_tensors = [x.to_gpu() for x in froog_tensors]

  out = torch_func(*torch_tensors)
  ret = froog_func(*froog_tensors)
  
  np.testing.assert_allclose(ret.to_cpu().data, out.detach().numpy(), atol=atol)

  if not forward_only:
    out.mean().backward()
    ret.mean().backward()

    for t, tt in zip(torch_tensors, froog_tensors):
      np.testing.assert_allclose(t.grad, tt.grad.to_cpu().data, atol=grad_atol)

  # test for speed
  # forward passes
    torch_fwd = timeit.Timer(functools.partial(torch_func, *torch_tensors)).timeit(5) * 1000/5
    froog_fwd = timeit.Timer(functools.partial(froog_func, *froog_tensors)).timeit(5) * 1000/5

  # backward passes
  if not forward_only:
    torch_fbp = timeit.Timer(functools.partial(lambda f,x: f(*x).mean().backward(), torch_func, torch_tensors)).timeit(5) * 1000/5
    froog_fbp = timeit.Timer(functools.partial(lambda f,x: f(*x).mean().backward(), froog_func, froog_tensors)).timeit(5) * 1000/5
  else:
    torch_fbp, froog_fbp = np.nan, np.nan

  print(f"shape: {repr(shape) : >32} torch/froog fwd: {torch_fwd:.2f}/{froog_fwd:.2f} ms ({float(froog_fwd/torch_fwd):.2f}x slower) bp: {torch_fbp - torch_fwd:.2f}/{froog_fbp - froog_fwd:.2f} ms ({float((froog_fbp - froog_fwd)/(torch_fbp - torch_fwd)):.2f}x slower)")


class TestOps(unittest.TestCase):
  def test_add(self):
    helper_test_op([(45,65), (45,65)], lambda x,y: x+y, Tensor.add)
  @unittest.skipUnless(GPU, "Requires GPU")
  def test_gpu_add(self):
    helper_test_op([(45,65), (45,65)], lambda x,y: x+y, Tensor.add, gpu=True)
  def test_sub(self):
    helper_test_op([(45,65), (45,65)], lambda x,y: x-y, Tensor.sub)
  def test_mul(self):
    helper_test_op([(45,65), (45,65)], lambda x,y: x*y, Tensor.mul)
  @unittest.skipUnless(GPU, "Requires GPU")
  def test_gpu_mul(self):
    helper_test_op([(45,65), (45,65)], lambda x,y: x*y, Tensor.mul, gpu=True)
  def test_div(self):
    # TODO: why needs more tolerance?
    helper_test_op([(45,65), (45,65)], lambda x,y: x/y, Tensor.div, atol=1e-3, grad_atol=1e-3)
  def test_pow(self):
    helper_test_op([(45,65), (45,65)], lambda x,y: x**y, Tensor.pow)
  def test_sqrt(self):
    helper_test_op([(45,65)], lambda x: x.sqrt(), Tensor.sqrt)
    
  def test_conv2d(self):
    for bs in [1,8]:
      for cin in [1,2,3]:
        for groups in [1,3] if cin == 3 else [1]:
          for H in [2,5]:
            for W in [2,3,5]:
              helper_test_op([(bs,cin,11,28), (6,cin//groups,H,W)],
                lambda x,w: torch.nn.functional.conv2d(x,w,groups=groups).relu(),
                lambda x,w: Tensor.conv2d(x,w,groups=groups).relu(), atol=2e-5, grad_atol=2e-6)
            
  # TODO: doesn't work for anything but (2,2)
  def test_maxpool_sizes(self):
    for size in [(2,2), (3,3), (3,2), (5,5), (5,1)]:
      helper_test_op([(32,2,110,28)],
        lambda x: torch.nn.functional.max_pool2d(x, kernel_size=size),
        lambda x: Tensor.max_pool2d(x, kernel_size=size))

  def test_maxpool2x2(self):
    helper_test_op([(32,2,110,28)], lambda x: torch.nn.functional.max_pool2d(x, (2,2)), Tensor.max_pool2d)

  def test_avgpool2x2(self):
    helper_test_op([(32,2,111,28)], lambda x: torch.nn.functional.avg_pool2d(x, (2,2)), Tensor.avg_pool2d)

  def test_strided_conv2d(self):
    bs = 4
    cin = 3
    H,W = 3,3
    helper_test_op([(bs,cin,11,28), (4,cin,H,W)],
      lambda x,w: torch.nn.functional.conv2d(x,w,stride=2).relu(),
      lambda x,w: Tensor.conv2d(x,w,stride=2).relu(), atol=2e-5, grad_atol=2e-6)
    helper_test_op([(bs,cin,11,28), (4,cin,H,W)],
      lambda x,w: torch.nn.functional.conv2d(x,w,stride=(2,1)).relu(),
      lambda x,w: Tensor.conv2d(x,w,stride=(2,1)).relu(), atol=2e-5, grad_atol=2e-6)

if __name__ == '__main__':
  unittest.main(verbosity=2) 
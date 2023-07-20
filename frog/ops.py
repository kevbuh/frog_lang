import numpy as np
from frog.tensor import Function, register
from frog.utils import im2col, col2im

# *********** Elementary Functions ***********
# Add, Mul, ReLU, Dot, Sum, Conv2D, Reshape 
# grad_output is the gradient of the loss with respect to the output of the operation.

class Add(Function):
  @staticmethod # @staticmethod doesn't require an instance of Add to work
  def forward(ctx, x, y):
    return x + y
  
  @staticmethod
  def backward(ctx, grad_output):
    return grad_output, grad_output 
register("add", Add)

class Mul(Function):
  @staticmethod
  def forward(ctx, x, y):
    ctx.save_for_backward(x, y)
    return x * y

  @staticmethod
  def backward(ctx, grad_output):
    x, y = ctx.saved_tensors
    return y * grad_output, x * grad_output
register("mul", Mul)


class ReLU(Function):
  @staticmethod
  def forward(ctx, input):
    ctx.save_for_backward(input)
    return np.maximum(input, 0)

  @staticmethod
  def backward(ctx, grad_output):
    (input,) = ctx.saved_tensors
    grad_input = grad_output.copy() # numpy only creates reference if you don't .copy()
    grad_input[input < 0] = 0
    return grad_input
register("relu", ReLU)


class Dot(Function):
  @staticmethod
  def forward(ctx, input, weight):
    ctx.save_for_backward(input, weight)
    return input.dot(weight)

  @staticmethod
  def backward(ctx, grad_output):
    input, weight = ctx.saved_tensors
    grad_input = grad_output.dot(weight.T)
    grad_weight = grad_output.T.dot(input).T
    return grad_input, grad_weight
register('dot', Dot)

class Sum(Function):
  """
  reduces its input tensor to a single value by summing all the elements
  """
  @staticmethod
  def forward(ctx, input):
    ctx.save_for_backward(input)
    return np.array([input.sum()])

  @staticmethod
  def backward(ctx, grad_output):
    (input,) = ctx.saved_tensors
    return grad_output * np.ones_like(input)
register("sum", Sum)

class LogSoftmax(Function):
  """
  converts a vector of numbers into a vector of probabilities
  probabilities of each value are proportional to the scale of each value 
  """
  @staticmethod
  def forward(ctx, input):
    def logsumexp(x):
      c = x.max(axis=1)
      return c + np.log(np.exp(x - c.reshape((-1, 1))).sum(axis=1)) # axis=1 refers to the columns

    output = input - logsumexp(input).reshape((-1, 1))
    ctx.save_for_backward(output)
    return output

  @staticmethod
  def backward(ctx, grad_output):
    (output,) = ctx.saved_tensors
    return grad_output - np.exp(output) * grad_output.sum(axis=1).reshape((-1, 1))
register("logsoftmax", LogSoftmax)

class Conv2D(Function): 
  @staticmethod
  def forward(ctx, input_image, conv_kernel):
    """
    https://github.com/vdumoulin/conv_arithmetic/blob/master/README.md
    WARNING: doesn't handle padding or strides yet
    Args:
      x.shape[0] 									  --> number of input examples (batch size)
      cout 			 								    --> number of output channels
      x.shape[2]-(H-1)					 	  --> non-padded height of conv output, need to subtract because this is an unpadded conv
      x.shape[3]-(W-1)						  --> width of output
    Shape: 
      (a, b, c, d)(e, f, g, h)      --> (a, e, c-(g-1), d-(h-1)) 
    """
    ctx.save_for_backward(input_image, conv_kernel)
    cout, cin, H, W = conv_kernel.shape
    conv_to_return = np.zeros((input_image.shape[0], cout, input_image.shape[2]-(H-1), input_image.shape[3]-(W-1)), dtype=conv_kernel.dtype)

    tw = conv_kernel.reshape(conv_kernel.shape[0], -1).T  # slice of kernel 

    for Y in range(conv_to_return.shape[2]):              # non_padded_height
      for X in range(conv_to_return.shape[3]):            # non_padded_width
        tx = input_image[:, :, Y:Y+H, X:X+W]
        tx = tx.reshape(input_image.shape[0], -1)
        conv_to_return[:, :, Y, X] = tx.dot(tw)
    return conv_to_return

  @staticmethod
  def backward(ctx, grad_output):
    x, conv_kernel = ctx.saved_tensors
    cout, cin, H, W = conv_kernel.shape
    dx, dw = np.zeros_like(x), np.zeros_like(conv_kernel)

    tw = conv_kernel.reshape(cout, -1) # slice of kernel

    for Y in range(grad_output.shape[2]):
      for X in range(grad_output.shape[3]):
        gg = grad_output[:, :, Y, X]                                                 # backprop gradients from previous layer 
        tx = x[:, :, Y:Y+H, X:X+W].reshape(x.shape[0], -1)                           # slice of tensor at current conv op                                                                                # 
        dw += gg.T.dot(tx).reshape(dw.shape)                                         # gradient with respect to conv kernel
        dx[:, :, Y:Y+H, X:X+W] += gg.dot(tw).reshape(dx.shape[0], dx.shape[1], H, W) # accumulate gradient of input (current multiply element in chain rule)
    return dx, dw
register('conv2d', Conv2D)


class FastConv2D(Function):
  """
  uses im2col
  https://leonardoaraujosantos.gitbook.io/artificial-inteligence/machine_learning/deep_learning/convolution_layer/making_faster
  """

  @staticmethod
  def forward(ctx, x, w):
    cout, cin, k_h, k_x = w.shape
    bs, oy, ox = x.shape[0], x.shape[2]-(k_h-1), x.shape[3]-(k_x-1)

    tw = w.reshape(cout, -1).T                              # each filter flattened into a row

    # im2col
    tx = im2col(x, k_h, k_x)

    # save the im2col output
    ctx.save_for_backward(tx, w)

    # now the conv is a GEMM
    # print(f"{tx.shape=}")
    # print(f"{tw.shape=}")

    ret = tx.dot(tw).reshape(oy, ox, bs, cout)

    return np.moveaxis(ret, [0,1,2,3], [2,3,0,1])            # reorders the axes (batch size, number of channels, height, width)

  @staticmethod
  def backward(ctx, grad_output):
    bs,_,oy,ox = grad_output.shape
    tx, w = ctx.saved_tensors
    cout,cin,H,W = w.shape

    tw = w.reshape(cout, -1)

    # order correctly
    gg = np.moveaxis(grad_output, [0,1,2,3], [2,3,0,1]).reshape(-1, cout)

    # dw is easy
    dw = gg.T.dot(tx).reshape(w.shape)

    # dx is harder
    dxi = gg.dot(tw)

    # im2col on forward, col2im on backward
    dx = col2im(dxi, H, W, oy+(H-1), ox+(W-1))

    return dx, dw
# register('conv2d', FastConv2D)


class Reshape(Function):
  @staticmethod
  def forward(ctx, x, shape):
    ctx.save_for_backward(x.shape)
    return x.reshape(shape)

  @staticmethod
  def backward(ctx, grad_output):
    in_shape, = ctx.saved_tensors
    return grad_output.reshape(in_shape), None
register('reshape', Reshape)
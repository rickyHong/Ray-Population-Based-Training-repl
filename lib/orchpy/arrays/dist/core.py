from typing import List
import numpy as np
import arrays.single as single
import orchpy as op

__all__ = ["BLOCK_SIZE", "DistArray", "assemble", "zeros", "ones", "copy",
           "eye", "triu", "tril", "blockwise_dot", "dot", "transpose", "add", "subtract", "eye2", "numpy_to_dist", "subblocks"]

BLOCK_SIZE = 10

class DistArray(object):
  def construct(self, shape, objrefs=None):
    self.shape = shape
    self.ndim = len(shape)
    self.num_blocks = [int(np.ceil(1.0 * a / BLOCK_SIZE)) for a in self.shape]
    self.objrefs = objrefs if objrefs is not None else np.empty(self.num_blocks, dtype=object)
    if self.num_blocks != list(self.objrefs.shape):
      raise Exception("The fields `num_blocks` and `objrefs` are inconsistent, `num_blocks` is {} and `objrefs` has shape {}".format(self.num_blocks, list(self.objrefs.shape)))

  def deserialize(self, primitives):
    (shape, objrefs) = primitives
    self.construct(shape, objrefs)

  def serialize(self):
    return (self.shape, self.objrefs)

  def __init__(self, shape=None):
    if shape is not None:
      self.construct(shape)

  @staticmethod
  def compute_block_lower(index, shape):
    if len(index) != len(shape):
      raise Exception("The fields `index` and `shape` must have the same length, but `index` is {} and `shape` is {}.".format(index, shape))
    return [elem * BLOCK_SIZE for elem in index]

  @staticmethod
  def compute_block_upper(index, shape):
    if len(index) != len(shape):
      raise Exception("The fields `index` and `shape` must have the same length, but `index` is {} and `shape` is {}.".format(index, shape))
    upper = []
    for i in range(len(shape)):
      upper.append(min((index[i] + 1) * BLOCK_SIZE, shape[i]))
    return upper

  @staticmethod
  def compute_block_shape(index, shape):
    lower = DistArray.compute_block_lower(index, shape)
    upper = DistArray.compute_block_upper(index, shape)
    return [u - l for (l, u) in zip(lower, upper)]

  @staticmethod
  def compute_num_blocks(shape):
    return [int(np.ceil(1.0 * a / BLOCK_SIZE)) for a in shape]

  def assemble(self):
    """Assemble an array on this node from a distributed array object reference."""
    first_block = op.pull(self.objrefs[(0,) * self.ndim])
    dtype = first_block.dtype
    result = np.zeros(self.shape, dtype=dtype)
    for index in np.ndindex(*self.num_blocks):
      lower = DistArray.compute_block_lower(index, self.shape)
      upper = DistArray.compute_block_upper(index, self.shape)
      result[[slice(l, u) for (l, u) in zip(lower, upper)]] = op.pull(self.objrefs[index])
    return result

  def __getitem__(self, sliced):
    # TODO(rkn): fix this, this is just a placeholder that should work but is inefficient
    a = self.assemble()
    return a[sliced]

@op.distributed([DistArray], [np.ndarray])
def assemble(a):
  return a.assemble()

# TODO(rkn): what should we call this method
@op.distributed([np.ndarray], [DistArray])
def numpy_to_dist(a):
  result = DistArray(a.shape)
  for index in np.ndindex(*result.num_blocks):
    lower = DistArray.compute_block_lower(index, a.shape)
    upper = DistArray.compute_block_upper(index, a.shape)
    result.objrefs[index] = op.push(a[[slice(l, u) for (l, u) in zip(lower, upper)]])
  return result

@op.distributed([List[int], str], [DistArray])
def zeros(shape, dtype_name):
  result = DistArray(shape)
  for index in np.ndindex(*result.num_blocks):
    result.objrefs[index] = single.zeros(DistArray.compute_block_shape(index, shape), dtype_name)
  return result

@op.distributed([List[int], str], [DistArray])
def ones(shape, dtype_name):
  result = DistArray(shape)
  for index in np.ndindex(*result.num_blocks):
    result.objrefs[index] = single.ones(DistArray.compute_block_shape(index, shape), dtype_name)
  return result

@op.distributed([DistArray], [DistArray])
def copy(a):
  result = DistArray(a.shape)
  for index in np.ndindex(*result.num_blocks):
    result.objrefs[index] = a.objrefs[index] # We don't need to actually copy the objects because cluster-level objects are assumed to be immutable.
  return result

@op.distributed([int, str], [DistArray])
def eye(dim, dtype_name):
  shape = [dim, dim]
  result = DistArray(shape)
  for (i, j) in np.ndindex(*result.num_blocks):
    if i == j:
      result.objrefs[i, j] = single.eye(DistArray.compute_block_shape([i, j], shape)[0], dtype_name)
    else:
      result.objrefs[i, j] = single.zeros(DistArray.compute_block_shape([i, j], shape), dtype_name)
  return result

# TODO(rkn): Support optional arguments so that we can make this part of eye.
@op.distributed([int, int, str], [DistArray])
def eye2(dim1, dim2, dtype_name):
  shape = [dim1, dim2]
  result = DistArray(shape)
  for (i, j) in np.ndindex(*result.num_blocks):
    block_shape = DistArray.compute_block_shape([i, j], shape)
    if i == j:
      result.objrefs[i, j] = single.eye2(block_shape[0], block_shape[1], dtype_name)
    else:
      result.objrefs[i, j] = single.zeros(block_shape, dtype_name)
  return result

@op.distributed([DistArray], [DistArray])
def triu(a):
  if a.ndim != 2:
    raise Exception("Input must have 2 dimensions, but a.ndim is " + str(a.ndim))
  result = DistArray(a.shape)
  for (i, j) in np.ndindex(*result.num_blocks):
    if i < j:
      result.objrefs[i, j] = single.copy(a.objrefs[i, j])
    elif i == j:
      result.objrefs[i, j] = single.triu(a.objrefs[i, j])
    else:
      result.objrefs[i, j] = single.zeros_like(a.objrefs[i, j])
  return result

@op.distributed([DistArray], [DistArray])
def tril(a):
  if a.ndim != 2:
    raise Exception("Input must have 2 dimensions, but a.ndim is " + str(a.ndim))
  result = DistArray(a.shape)
  for (i, j) in np.ndindex(*result.num_blocks):
    if i > j:
      result.objrefs[i, j] = single.copy(a.objrefs[i, j])
    elif i == j:
      result.objrefs[i, j] = single.tril(a.objrefs[i, j])
    else:
      result.objrefs[i, j] = single.zeros_like(a.objrefs[i, j])
  return result

@op.distributed([np.ndarray, None], [np.ndarray])
def blockwise_dot(*matrices):
  n = len(matrices)
  if n % 2 != 0:
    raise Exception("blockwise_dot expects an even number of arguments, but len(matrices) is {}.".format(n))
  shape = (matrices[0].shape[0], matrices[n / 2].shape[1])
  result = np.zeros(shape)
  for i in range(n / 2):
    result += np.dot(matrices[i], matrices[n / 2 + i])
  return result

@op.distributed([DistArray, DistArray], [DistArray])
def dot(a, b):
  if a.ndim != 2:
    raise Exception("dot expects its arguments to be 2-dimensional, but a.ndim = {}.".format(a.ndim))
  if b.ndim != 2:
    raise Exception("dot expects its arguments to be 2-dimensional, but b.ndim = {}.".format(b.ndim))
  if a.shape[1] != b.shape[0]:
    raise Exception("dot expects a.shape[1] to equal b.shape[0], but a.shape = {} and b.shape = {}.".format(a.shape, b.shape))
  shape = [a.shape[0], b.shape[1]]
  result = DistArray(shape)
  for (i, j) in np.ndindex(*result.num_blocks):
    args = list(a.objrefs[i, :]) + list(b.objrefs[:, j])
    result.objrefs[i, j] = blockwise_dot(*args)
  return result

# This is not in numpy, should we expose this?
@op.distributed([DistArray, List[int], None], [DistArray])
def subblocks(a, *ranges):
  """
  This function produces a distributed array from a subset of the blocks in the `a`. The result and `a` will have the same number of dimensions.For example,
      subblocks(a, [0, 1], [2, 4])
  will produce a DistArray whose objrefs are
      [[a.objrefs[0, 2], a.objrefs[0, 4]],
       [a.objrefs[1, 2], a.objrefs[1, 4]]]
  We allow the user to pass in an empty list [] to indicate the full range.
  """
  ranges = list(ranges)
  if len(ranges) != a.ndim:
    raise Exception("sub_blocks expects to receive a number of ranges equal to a.ndim, but it received {} ranges and a.ndim = {}.".format(len(ranges), a.ndim))
  for i in range(len(ranges)):
    if ranges[i] == []: # We allow the user to pass in an empty list to indicate the full range
      ranges[i] = range(a.num_blocks[i])
    if not np.alltrue(ranges[i] == np.sort(ranges[i])):
      raise Exception("Ranges passed to sub_blocks must be sorted, but the {}th range is {}.".format(i, ranges[i]))
    if ranges[i][0] < 0:
      raise Exception("Values in the ranges passed to sub_blocks must be at least 0, but the {}th range is {}.".format(i, ranges[i]))
    if ranges[i][-1] >= a.num_blocks[i]:
        raise Exception("Values in the ranges passed to sub_blocks must be less than the relevant number of blocks, but the {}th range is {}, and a.num_blocks = {}.".format(i, ranges[i], a.num_blocks))
  last_index = [r[-1] for r in ranges]
  last_block_shape = DistArray.compute_block_shape(last_index, a.shape)
  shape = [(len(ranges[i]) - 1) * BLOCK_SIZE + last_block_shape[i] for i in range(a.ndim)]
  result = DistArray(shape)
  for index in np.ndindex(*result.num_blocks):
    print tuple([ranges[i][index[i]] for i in range(a.ndim)])
    result.objrefs[index] = a.objrefs[tuple([ranges[i][index[i]] for i in range(a.ndim)])]
  return result

@op.distributed([DistArray], [DistArray])
def transpose(a):
  if a.ndim != 2:
    raise Exception("transpose expects its argument to be 2-dimensional, but a.ndim = {}, a.shape = {}.".format(a.ndim, a.shape))
  result = DistArray([a.shape[1], a.shape[0]])
  for i in range(result.num_blocks[0]):
    for j in range(result.num_blocks[1]):
      result.objrefs[i, j] = single.transpose(a.objrefs[j, i])
  return result

# TODO(rkn): support broadcasting?
@op.distributed([DistArray, DistArray], [DistArray])
def add(x1, x2):
  if x1.shape != x2.shape:
    raise Exception("add expects arguments `x1` and `x2` to have the same shape, but x1.shape = {}, and x2.shape = {}.".format(x1.shape, x2.shape))
  result = DistArray(x1.shape)
  for index in np.ndindex(*result.num_blocks):
    result.objrefs[index] = single.add(x1.objrefs[index], x2.objrefs[index])
  return result

# TODO(rkn): support broadcasting?
@op.distributed([DistArray, DistArray], [DistArray])
def subtract(x1, x2):
  if x1.shape != x2.shape:
    raise Exception("subtract expects arguments `x1` and `x2` to have the same shape, but x1.shape = {}, and x2.shape = {}.".format(x1.shape, x2.shape))
  result = DistArray(x1.shape)
  for index in np.ndindex(*result.num_blocks):
    result.objrefs[index] = single.subtract(x1.objrefs[index], x2.objrefs[index])
  return result
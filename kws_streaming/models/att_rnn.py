# coding=utf-8
# Copyright 2019 The Google Research Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""BiLSTM model with attention."""
from kws_streaming.layers import speech_features
from kws_streaming.layers.compat import tf
from kws_streaming.models.utils import parse


def model_parameters(parser_nn):
  """BiLSTM attention model parameters."""

  parser_nn.add_argument(
      '--cnn_filters',
      type=str,
      default='10,1',
      help='Number of output filters in the convolution layers',
  )
  parser_nn.add_argument(
      '--cnn_kernel_size',
      type=str,
      default='(5,1),(5,1)',
      help='Heights and widths of the 2D convolution window',
  )
  parser_nn.add_argument(
      '--cnn_act',
      type=str,
      default="'relu','relu'",
      help='Activation function in the convolution layers',
  )
  parser_nn.add_argument(
      '--cnn_dilation_rate',
      type=str,
      default='(1,1),(1,1)',
      help='Dilation rate to use for dilated convolutions',
  )
  parser_nn.add_argument(
      '--cnn_strides',
      type=str,
      default='(1,1),(1,1)',
      help='Strides of the convolution layers along the height and width',
  )
  parser_nn.add_argument(
      '--rnn_layers',
      type=int,
      default=2,
      help='number of RNN layers (each RNN is wrapped by Bidirectional)',
  )
  parser_nn.add_argument(
      '--rnn_type',
      type=str,
      default='lstm',
      help='RNN type: it can be rnn or lstm',
  )
  parser_nn.add_argument(
      '--rnn_units',
      type=int,
      default=64,
      help='units number in RNN cell',
  )
  parser_nn.add_argument(
      '--dropout1',
      type=float,
      default=0.5,
      help='Percentage of data dropped',
  )
  parser_nn.add_argument(
      '--units2',
      type=str,
      default='64,32',
      help='Number of units in the last set of hidden layers',
  )
  parser_nn.add_argument(
      '--act2',
      type=str,
      default="'relu','linear'",
      help='Activation function of the last set of hidden layers',
  )


def model(flags):
  """BiLSTM attention model.

  It is based on paper:
  A neural attention model for speech command recognition
  https://arxiv.org/pdf/1808.08929.pdf

  Args:
    flags: data/model parameters

  Returns:
    Keras model for training
  """

  rnn_types = {'lstm': tf.keras.layers.LSTM, 'gru': tf.keras.layers.GRU}

  if flags.rnn_type not in rnn_types:
    ValueError('not supported RNN type ', flags.rnn_type)
  rnn = rnn_types[flags.rnn_type]

  input_audio = tf.keras.layers.Input(
      shape=(flags.desired_samples,), batch_size=flags.batch_size)

  net = speech_features.SpeechFeatures(
      frame_size_ms=flags.window_size_ms,
      frame_step_ms=flags.window_stride_ms,
      sample_rate=flags.sample_rate,
      use_tf_fft=flags.use_tf_fft,
      preemph=flags.preemph,
      window_type=flags.window_type,
      mel_num_bins=flags.mel_num_bins,
      mel_lower_edge_hertz=flags.mel_lower_edge_hertz,
      mel_upper_edge_hertz=flags.mel_upper_edge_hertz,
      mel_non_zero_only=flags.mel_non_zero_only,
      fft_magnitude_squared=flags.fft_magnitude_squared,
      dct_num_features=flags.dct_num_features)(
          input_audio)

  net = tf.keras.backend.expand_dims(net)
  for filters, kernel_size, activation, dilation_rate, strides in zip(
      parse(flags.cnn_filters), parse(flags.cnn_kernel_size),
      parse(flags.cnn_act), parse(flags.cnn_dilation_rate),
      parse(flags.cnn_strides)):
    net = tf.keras.layers.Conv2D(
        filters=filters,
        kernel_size=kernel_size,
        activation=activation,
        dilation_rate=dilation_rate,
        strides=strides,
        padding='same')(
            net)
    net = tf.keras.layers.BatchNormalization()(net)

  shape = net.shape
  # input net dimension: [batch, time, feature, channels]
  # reshape dimension: [batch, time, feature * channels]
  # so that GRU/RNN can process it
  net = tf.keras.layers.Reshape((-1, shape[2] * shape[3]))(net)

  # dims: [batch, time, feature]
  for _ in range(flags.rnn_layers):
    net = tf.keras.layers.Bidirectional(
        rnn(flags.rnn_units, return_sequences=True, unroll=True))(
            net)
  feature_dim = net.shape[-1]
  middle = net.shape[1] // 2  # index of middle point of sequence

  # feature vector at middle point [batch, feature]
  mid_feature = net[:, middle, :]
  # apply one projection layer with the same dim as input feature
  query = tf.keras.layers.Dense(feature_dim)(mid_feature)

  # attention weights [batch, time]
  att_weights = tf.keras.layers.Dot(axes=[1, 2])([query, net])
  att_weights = tf.keras.layers.Softmax(name='attSoftmax')(att_weights)

  # apply attention weights [batch, feature]
  net = tf.keras.layers.Dot(axes=[1, 1])([att_weights, net])

  net = tf.keras.layers.Dropout(rate=flags.dropout1)(net)

  for units, activation in zip(parse(flags.units2), parse(flags.act2)):
    net = tf.keras.layers.Dense(units=units, activation=activation)(net)

  net = tf.keras.layers.Dense(units=flags.label_count)(net)
  return tf.keras.Model(input_audio, net)

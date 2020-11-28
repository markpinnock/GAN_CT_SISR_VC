import numpy as np
import tensorflow as tf
import tensorflow.keras as keras
from tensorflow.python.eager import context
from tensorflow.python.ops import gen_math_ops, nn_ops


""" Fade in, minibatch std and pixel norm implementation
    inspired by https://machinelearningmastery.com/how-to-train-a-progressive-growing-gan-in-keras-for-synthesizing-faces/ """

#-------------------------------------------------------------------------
""" Overloaded implementation of Dense layer for equalised learning rate,
    taken from https://github.com/tensorflow/tensorflow/blob/v2.3.1/tensorflow/python/keras/layers/core.py """

class EqDense(keras.layers.Dense):

    def __init__(self, **kwargs):
        """ Initialise Dense with the usual arguments """

        super(EqDense, self).__init__(**kwargs)

        self.weight_scale = None
    
    def call(self, inputs, gain=tf.sqrt(2.0)):
        """ Overloaded call to apply weight scale at runtime """

        if self.weight_scale is None:
            fan_in = tf.reduce_prod(self.kernel.shape[:-1])
            self.weight_scale = gain / tf.sqrt(tf.cast(fan_in, tf.float32))

        # Perform dense layer matmul
        outputs = gen_math_ops.MatMul(a=inputs, b=self.kernel * self.weight_scale)
        outputs = nn_ops.bias_add(outputs, self.bias)
        
        # Activation not needed
        return outputs

#-------------------------------------------------------------------------
""" Overloaded implementation of Conv2D layer for equalised learning rate,
    taken from https://github.com/tensorflow/tensorflow/blob/master/tensorflow/python/keras/layers/convolutional.py """

class EqLrConv2D(keras.layers.Conv2D):

    def __init__(self, **kwargs):
        """ Initialise with the usual arguments """

        super(EqLrConv2D, self).__init__(**kwargs)
        

        if self.weight_scale is None:
            fan_in = tf.reduce_prod(self.kernel.shape[:-1])
            self.weight_scale = gain / tf.sqrt(tf.cast(fan_in, tf.float32))

        # Perform convolution and add bias weights
        outputs = self._convolution_op(inputs, self.kernel * self.weight_scale)
        
#-------------------------------------------------------------------------
""" Overloaded implementation of Conv2DTranspose layer for equalised learning
    rate - will work only for (1, 1, 1) -> (4, 4, N) transpose conv - taken from
    https://github.com/tensorflow/tensorflow/blob/master/tensorflow/python/keras/layers/convolutional.py"""

class EqLrConv2DTranspose(keras.layers.Conv2DTranspose):
    
    def __init__(self, **kwargs):
        """ Initialise with the usual arguments """

        super(EqLrConv2DTranspose, self).__init__(**kwargs)
        self.weight_scale = None

    def call(self, inputs, gain=tf.sqrt(2.0)):
        """ Overloaded call method applies weight scale at runtime """
    
        if not self.weight_scale:
            fan_in = tf.reduce_prod(self.kernel.shape[:-1])
            self.weight_scale = gain / tf.sqrt(tf.cast(fan_in, tf.float32))
        
        # 4x4xN output only
        inputs_shape = inputs.shape
        batch_size = inputs_shape[0]
        out_height, out_width = 4, 4
        output_shape = (batch_size, out_height, out_width, self.filters)
        output_shape_tensor = tf.stack(output_shape)
        
        outputs = keras.backend.conv2d_transpose(
            inputs,
            self.kernel * self.weight_scale,
            output_shape_tensor,
            strides=self.strides,
            padding=self.padding,
            data_format=self.data_format,
            dilation_rate=self.dilation_rate)

        if not context.executing_eagerly():
            out_shape = self.compute_output_shape(inputs.shape)
            outputs.set_shape(out_shape)

        if self.use_bias:
            outputs = tf.nn.bias_add(outputs,self.bias, data_format="NHWC")

        # Activation not needed in call()
        return outputs

#-------------------------------------------------------------------------
""" Fade in layer - interpolates between two layers by factor alpha """

def fade_in(alpha, old, new):
    return (1.0 - alpha) * old + alpha * new

#-------------------------------------------------------------------------
""" Minibatch statistics layer """

def mb_stddev(x):
    mean_std_dev = tf.reduce_mean(tf.math.reduce_std(x, axis=0, keepdims=True), keepdims=True)
    stat_channel = tf.tile(mean_std_dev, x.shape[:-1] + [1])
    
    return tf.concat([x, stat_channel], axis=-1)

#-------------------------------------------------------------------------
""" Implementation of pixel normalisation layer """

def pixel_norm(x):
    x_sq = tf.reduce_mean(tf.square(x), axis=-1, keepdims=True)
    x_norm = tf.sqrt(x_sq + 1e-8)
    
    return x / x_norm


#-------------------------------------------------------------------------
""" Generic GAN block - not currently used """

class GANBlock(keras.layers.Layer):
    def __init__(self, nc, initialiser, weight_const, batchnorm, transpose):
        super(GANBlock, self).__init__()
        self.batchnorm = batchnorm
        # TODO: change BN to LN in WGAN-GP
        if transpose:
            self.conv = keras.layers.Conv2DTranspose(nc, (4, 4), strides=(2, 2), padding='SAME', use_bias=True, kernel_initializer=initialiser, kernel_constraint=weight_const)
        else:
            self.conv = keras.layers.Conv2D(nc, (4, 4), strides=(2, 2), padding='SAME', use_bias=True, kernel_initializer=initialiser, kernel_constraint=weight_const)
        
        if self.batchnorm:
            self.bn = keras.layers.BatchNormalization()
        
        def call(self, x):
            x = self.conv(x)

            if self.batchnorm:
                x = self.bn(x)
            
            return tf.nn.leaky_relu(x, alpha=0.2)

#-------------------------------------------------------------------------
""" Convolutional layer """

# class

#-------------------------------------------------------------------------
""" Progressive GAN Discriminator block """

class ProgGANDiscBlock(keras.layers.Layer):
    def __init__(self, ch, res, next_block, config, weight_const):
        super(ProgGANDiscBlock, self).__init__()
        double_ch = np.min([ch * 2, config["MAX_CHANNELS"]])

        if config["MODEL"] == "progressive":
            Dense = EqDense
            Conv2D = EqLrConv2D
            initialiser = keras.initializers.RandomNormal(0, 1)
        else:
            Dense = keras.layers.Dense
            Conv2D = keras.layers.Conv2D 
            initialiser = keras.initializers.RandomNormal(0, 0.02)

        self.next_block = next_block
        self.from_rgb = Conv2D(filters=ch, kernel_size=(1, 1), strides=(1, 1), padding="SAME", kernel_initializer=initialiser, kernel_constraint=weight_const)
        
        # If this is last discriminator block, collapse to prediction
        if next_block == None:
            self.conv = Conv2D(filters=double_ch, kernel_size=(3, 3), strides=(1, 1), padding="SAME", kernel_initializer=initialiser, kernel_constraint=weight_const)
            self.flat = keras.layers.Flatten()
            self.dense = Dense(units=res, kernel_initializer=initialiser, kernel_constraint=weight_const)
            self.out = Dense(units=1, kernel_initializer=initialiser, kernel_constraint=weight_const)
        
        # If next blocks exist, conv and downsample
        else:
            self.conv1 = Conv2D(filters=ch, kernel_size=(3, 3), strides=(1, 1), padding="SAME", kernel_initializer=initialiser, kernel_constraint=weight_const)
            self.conv2 = Conv2D(filters=double_ch, kernel_size=(3, 3), strides=(1, 1), padding="SAME", kernel_initializer=initialiser, kernel_constraint=weight_const)
            self.downsample = keras.layers.AveragePooling2D()

    def call(self, x, alpha=None, first_block=True):
        
        # If fade in, pass downsampled image into next block and cache
        if first_block and alpha != None and self.next_block != None:
            next_rgb = self.downsample(x)
            next_rgb = tf.nn.leaky_relu(self.next_block.from_rgb(next_rgb), alpha=0.2)

        # If the very first block, perform 1x1 conv on rgb
        if first_block:
            x = tf.nn.leaky_relu(self.from_rgb(x), alpha=0.2)

        # If this is not the last block
        if self.next_block != None:
            x = tf.nn.leaky_relu(self.conv1(x), alpha=0.2)
            x = tf.nn.leaky_relu(self.conv2(x), alpha=0.2)
            x = self.downsample(x)

            # If fade in, merge with cached layer
            if first_block and alpha != None and self.next_block != None:
                x = fade_in(alpha, next_rgb, x)
            
            x = self.next_block(x, alpha=None, first_block=False)
        
        # If this is the last block
        else:
            x = mb_stddev(x)
            x = tf.nn.leaky_relu(self.conv(x), alpha=0.2)
            x = self.flat(x)
            x = tf.nn.leaky_relu(self.dense(x))
            x = self.out(x, gain=1) # Gain as in original implementation

        return x

#-------------------------------------------------------------------------
""" Progressive GAN Generator block """

class ProgGANGenBlock(keras.layers.Layer):
    def __init__(self, ch, res, prev_block, config, weight_const):
        super(ProgGANGenBlock, self).__init__()

        self.prev_block = prev_block

        if config["MODEL"] == "progressive":
            Dense = EqDense
            Conv2D = EqLrConv2D
            Conv2DTranspose = EqLrConv2DTranspose
            initialiser = keras.initializers.RandomNormal(0, 1)
        else:
            Dense = keras.layers.Dense
            Conv2D = keras.layers.Conv2D
            Conv2DTranspose = keras.layers.Conv2DTranspose
            initialiser = keras.initializers.RandomNormal(0, 0.02)
        
        # If this is first generator block, pass latent noise into dense and reshape
        if prev_block == None:
            self.dense = Dense(units=config["LATENT_DIM"] * res * res, kernel_initializer=initialiser, kernel_constraint=weight_const)
            self.reshaped = keras.layers.Reshape((res, res, config["LATENT_DIM"]))
            self.conv = Conv2D(filters=ch, kernel_size=(3, 3), strides=(1, 1), padding="SAME", kernel_initializer=initialiser, kernel_constraint=weight_const)
        
        # If previous blocks exist, we use those
        else:
            self.upsample = keras.layers.UpSampling2D(interpolation="bilinear")
            self.conv1 = Conv2D(filters=ch, kernel_size=(3, 3), strides=(1, 1), padding="SAME", kernel_initializer=initialiser, kernel_constraint=weight_const)
            self.conv2 = Conv2D(filters=ch, kernel_size=(3, 3), strides=(1, 1), padding="SAME", kernel_initializer=initialiser, kernel_constraint=weight_const)
        
        # Output to rgb
        self.to_rgb = Conv2D(filters=3, kernel_size=(1, 1), strides=(1, 1), padding="SAME", kernel_initializer=initialiser, kernel_constraint=weight_const)

    def call(self, x, alpha=None):

        # If first block, upsample noise
        if self.prev_block == None:
            x = pixel_norm(tf.nn.leaky_relu(self.dense(x, gain=tf.sqrt(2.0) / 4), alpha=0.2)) # As in original implementation
            x = self.reshaped(x)
            x = pixel_norm(tf.nn.leaky_relu(self.conv(x), alpha=0.2))
        
        # If not first block, upsample to_rgb and cache for fade in
        else:
            prev_x, prev_rgb = self.prev_block(x, alpha=None)
            prev_x = self.upsample(prev_x)
            x = pixel_norm(tf.nn.leaky_relu(self.conv1(prev_x), alpha=0.2))
            x = pixel_norm(tf.nn.leaky_relu(self.conv2(x), alpha=0.2))

        # Create output image
        rgb = self.to_rgb(x)

        # If fade in, merge cached prev block and this block
        if alpha != None and self.prev_block != None:
            prev_rgb = self.upsample(prev_rgb)
            rgb = fade_in(alpha, prev_rgb, rgb)
        
        return x, rgb

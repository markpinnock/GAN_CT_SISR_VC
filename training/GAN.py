import tensorflow as tf
import tensorflow.keras as keras

from utils.TrainFuncs import least_square_loss, wasserstein_loss, gradient_penalty, WeightClipConstraint


class Discriminator(keras.Model):

    """ Discriminator model for GAN
        - d_nc: number of channels in first layer
        - initaliser: e.g. keras.initalizers.RandomNormal()
        - clip: True/False, whether to clip layer weights """

    def __init__(self, d_nc, initialiser, clip):
        super(Discriminator, self).__init__()
        self.initialiser = initialiser

        if clip:
            self.weight_clip = WeightClipConstraint(0.01)
        else:
            self.weight_clip = None

        self.conv1 = keras.layers.Conv2D(d_nc, (4, 4), strides=(2, 2), padding='SAME', use_bias=True, kernel_initializer=self.initialiser, kernel_constraint=self.weight_clip)
        self.conv2 = keras.layers.Conv2D(d_nc * 2, (4, 4), strides=(2, 2), padding='SAME', use_bias=True, kernel_initializer=self.initialiser, kernel_constraint=self.weight_clip)
        self.conv3 = keras.layers.Conv2D(d_nc * 4, (4, 4), strides=(2, 2), padding='SAME', use_bias=True, kernel_initializer=self.initialiser, kernel_constraint=self.weight_clip)
        self.conv4 = keras.layers.Conv2D(d_nc * 8, (4, 4), strides=(2, 2), padding='SAME', use_bias=True, kernel_initializer=self.initialiser, kernel_constraint=self.weight_clip)
        self.conv5 = keras.layers.Conv2D(1, (4, 4), strides=(1, 1), padding='VALID', use_bias=True, kernel_initializer=self.initialiser, kernel_constraint=self.weight_clip)
        # TODO: change BN to LN in WGAN-GP
        self.bn2 = keras.layers.BatchNormalization()
        self.bn3 = keras.layers.BatchNormalization()
        self.bn4 = keras.layers.BatchNormalization()

    def call(self, x, training):
        h1 = tf.nn.leaky_relu(self.conv1(x), alpha=0.2)
        h2 = tf.nn.leaky_relu(self.bn2(self.conv2(h1), training=training), alpha=0.2)
        h3 = tf.nn.leaky_relu(self.bn3(self.conv3(h2), training=training), alpha=0.2)
        h4 = tf.nn.leaky_relu(self.bn4(self.conv4(h3), training=training), alpha=0.2)

        return tf.squeeze(self.conv5(h4))


class Generator(keras.Model):

    """ Generator model for GAN
        - latient_dims: size of latent distribution
        - g_nc: number of channels in first layer
        - initaliser: e.g. keras.initalizers.RandomNormal() """

    def __init__(self, latent_dims, g_nc, initialiser):
        super(Generator, self).__init__()
        self.initialiser = initialiser

        self.reshaped = keras.layers.Reshape((1, 1, latent_dims))
        self.tconv1 = keras.layers.Conv2DTranspose(g_nc * 8, (4, 4), strides=(1, 1), padding='VALID', use_bias=True, kernel_initializer=self.initialiser)
        self.tconv2 = keras.layers.Conv2DTranspose(g_nc * 4, (4, 4), strides=(2, 2), padding='SAME', use_bias=True, kernel_initializer=self.initialiser)
        self.tconv3 = keras.layers.Conv2DTranspose(g_nc * 2, (4, 4), strides=(2, 2), padding='SAME', use_bias=True, kernel_initializer=self.initialiser)
        self.tconv4 = keras.layers.Conv2DTranspose(g_nc, (4, 4), strides=(2, 2), padding='SAME', use_bias=True, kernel_initializer=self.initialiser)
        self.tconv5 = keras.layers.Conv2DTranspose(3, (4, 4), strides=(2, 2), padding='SAME', use_bias=True, kernel_initializer=self.initialiser)

        self.bn1 = keras.layers.BatchNormalization()
        self.bn2 = keras.layers.BatchNormalization()
        self.bn3 = keras.layers.BatchNormalization()
        self.bn4 = keras.layers.BatchNormalization()

    def call(self, x, training):
        hr = self.reshaped(x)
        h1 = tf.nn.relu(self.bn1(self.tconv1(hr), training=training))
        h2 = tf.nn.relu(self.bn2(self.tconv2(h1), training=training))
        h3 = tf.nn.relu(self.bn3(self.tconv3(h2), training=training))
        h4 = tf.nn.relu(self.bn4(self.tconv4(h3), training=training))

        return tf.nn.tanh(self.tconv5(h4))


class GAN(keras.Model):

    """ GAN class
        - latent_dims: size of generator latent distribution
        - g_nc: number of channels in generator first layer
        - d_nc: number of channels in discriminator first layer
        - g_optimiser: generator optimiser e.g. keras.optimizers.Adam()
        - d_optimiser: discriminator optimiser e.g. keras.optimizers.Adam()
        - GAN_type: 'original', 'least_square', 'wasserstein' or 'wasserstein-GP'
        - n_critic: number of discriminator/critic training runs (5 in WGAN, 1 otherwise) """

    def __init__(self, latent_dims, g_nc, d_nc, g_optimiser, d_optimiser, GAN_type, n_critic):
        super(GAN, self).__init__()
        self.GAN_type = GAN_type
        self.latent_dims = latent_dims
        self.initialiser = keras.initializers.RandomNormal(0, 0.02)

        # Choose appropriate loss and initialise metrics
        self.loss_dict = {
            "original": keras.losses.BinaryCrossentropy(from_logits=True),
            "least_square": least_square_loss,
            "wasserstein": wasserstein_loss,
            "wasserstein-GP": wasserstein_loss
            }

        self.metric_dict = {
            "g_metric": keras.metrics.Mean(),
            "d_metric_1": keras.metrics.Mean(),
            "d_metric_2": keras.metrics.Mean()
        }

        # Set up real/fake labels
        if GAN_type == "wasserstein":
            self.d_real_label = -1.0
            self.d_fake_label = 1.0
            self.g_label = -1.0
            clip = True
        elif GAN_type == "wasserstein-GP":
            self.d_real_label = -1.0
            self.d_fake_label = 1.0
            self.g_label = -1.0
            clip = False
        else:
            self.d_real_label = 0.0
            self.d_fake_label = 1.0
            self.g_label = 0.0
            clip = False

        self.loss = self.loss_dict[GAN_type]
        self.Generator = Generator(latent_dims, g_nc, self.initialiser)
        self.Discriminator = Discriminator(d_nc, self.initialiser, clip)
        self.g_optimiser = g_optimiser
        self.d_optimiser = d_optimiser
        self.n_critic = n_critic
    
    def compile(self, g_optimiser, d_optimiser, loss_key):
        # Not currently used
        raise NotImplementedError
        super(GAN, self).compile()
        self.g_optimiser = g_optimiser
        self.d_optimiser = d_optimiser
        self.loss = self.loss_dict[loss_key]
    
    def train_step(self, real_images):
        # Determine labels and size of mb for each critic training run
        # (size of real_images = minibatch size * number of critic runs)
        mb_size = real_images.shape[0] // self.n_critic

        d_labels = tf.concat(
            [tf.ones((mb_size, 1)) * self.d_fake_label,
             tf.ones((mb_size, 1)) * self.d_real_label
             ], axis=0)
            
        g_labels = tf.ones((mb_size, 1)) * self.g_label

        # TODO: ADD NOISE TO LABELS AND/OR IMAGES

        # Critic training loop
        for idx in range(self.n_critic):
            # Select minibatch of real images and generate fake images
            d_real_batch = real_images[idx * mb_size:(idx + 1) * mb_size, :, :, :]
            latent_noise = tf.random.normal((mb_size, self.latent_dims), dtype=tf.float32)
            d_fake_images = self.Generator(latent_noise, training=True)

            # Get gradients from critic predictions and update weights
            with tf.GradientTape() as d_tape:
                d_pred_fake = self.Discriminator(d_fake_images, training=True)
                d_pred_real = self.Discriminator(d_real_batch, training=True)
                d_predictions = tf.concat([d_pred_fake, d_pred_real], axis=0)
                d_loss_1 = self.loss(d_labels[0:mb_size], d_predictions[0:mb_size]) # Fake
                d_loss_2 = self.loss(d_labels[mb_size:], d_predictions[mb_size:]) # Real
                d_loss = 0.5 * d_loss_1 + 0.5 * d_loss_2
            
                # Gradient penalty if indicated
                if self.GAN_type == "wasserstein-GP":
                    grad_penalty = gradient_penalty(d_real_batch, d_fake_images, self.Discriminator)
                    d_loss += 10 * grad_penalty
            
            d_grads = d_tape.gradient(d_loss, self.Discriminator.trainable_variables)
            self.d_optimiser.apply_gradients(zip(d_grads, self.Discriminator.trainable_variables))

            # Update metrics
            self.metric_dict["d_metric_1"].update_state(d_loss_1)
            self.metric_dict["d_metric_2"].update_state(d_loss_2)

        # Generator training
        noise = tf.random.normal((mb_size, self.latent_dims), dtype=tf.float32)
        
        # TODO: ADD NOISE TO LABELS AND/OR IMAGES

        # Get gradients from critic predictions of generated fake images and update weights
        with tf.GradientTape() as g_tape:
            g_fake_images = self.Generator(noise, training=True)
            g_predictions = self.Discriminator(g_fake_images, training=True)
            g_loss = self.loss(g_labels, g_predictions)
        
        g_grads = g_tape.gradient(g_loss, self.Generator.trainable_variables)
        self.g_optimiser.apply_gradients(zip(g_grads, self.Generator.trainable_variables))

        # Update metric
        self.metric_dict["g_metric"].update_state(g_loss)

        return self.metric_dict

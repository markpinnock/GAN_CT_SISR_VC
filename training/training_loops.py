import datetime
import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf


def trace_graph(model, input_zeros):

    @tf.function
    def trace(x):
        return model(x, 4)

    current_time = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir = "C:/Users/roybo/OneDrive - University College London/PhD/PhD_Prog/009_GAN_CT/logs/" + current_time
    summary_writer = tf.summary.create_file_writer(log_dir)

    tf.summary.trace_on(graph=True)
    trace(input_zeros)

    with summary_writer.as_default():
        tf.summary.trace_export("graph", step=0)


def Pix2Pix_training_loop(mb_size, epochs, Model, data, latent_sample, scale, fade=False):
    SAVE_PATH = "C:/Users/roybo/OneDrive - University College London/PhD/PhD_Prog/009_GAN_CT/imgs/test/"
    
    if fade:
        num_batches = 10000 // mb_size
        num_iter = num_batches * epochs
    else:
        num_iter = 0
    
    Model.fade_set(num_iter)

    # TODO: convert dataloader to alter scale
    down_samp = 64 // scale
    scale_idx = int(np.log2(scale / 4))

    for epoch in range(epochs):

        Model.metric_dict["g_metric"].reset_states()
        Model.metric_dict["d_metric_1"].reset_states()
        Model.metric_dict["d_metric_2"].reset_states()

        for imgs in data:
            imgs = imgs[:, ::down_samp, ::down_samp, :]
            _ = Model.train_step(imgs, scale=scale_idx)

        print(f"Scale {scale} Fade {fade} Ep {epoch + 1}, G: {Model.metric_dict['g_metric'].result():.4f}, D1: {Model.metric_dict['d_metric_1'].result():.4f}, D2: {Model.metric_dict['d_metric_2'].result():.4f}")

        # Generate example images
        if (epoch + 1) % 1 == 0:
            pred = Model.Generator(latent_sample, scale=scale_idx, training=False)

            fig = plt.figure(figsize=(4,4))

            for i in range(pred.shape[0]):
                plt.subplot(4, 4, i+1)
                plt.imshow(pred[i, :, :, :] / 2 + 0.5)
                plt.axis('off')

            plt.tight_layout()
            plt.savefig(f"{SAVE_PATH}/scale_{scale_idx}_fade_{int(fade)}_epoch_{epoch + 1:02d}.png", dpi=250)
            plt.close()

        # Save checkpoint
        # if (epoch + 1) % 10 == 0 and SAVE_CKPT:
        #     check_path = f"{SAVE_PATH}models/{RES}/"

        #     if not os.path.exists(check_path):
        #         os.mkdir(check_path)
            
        #     G_check_name = f"{SAVE_PATH}models/{RES}/G_{epoch + 1:04d}.ckpt"
        #     D_check_name = f"{SAVE_PATH}models/{RES}/D_{epoch + 1:04d}.ckpt"
        #     Generator.save_weights(G_check_name)
        #     Discriminator.save_weights(D_check_name)
    
    return Model
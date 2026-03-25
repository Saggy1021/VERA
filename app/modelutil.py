import os 
import tensorflow as tf
try:
    # TF 2.16+ uses Keras 3 — use tf_keras for backward compat
    import tf_keras as keras
    from tf_keras import Sequential
    from tf_keras.layers import Conv3D, LSTM, Dense, Dropout, Bidirectional, MaxPool3D, Activation, Reshape, SpatialDropout3D, BatchNormalization, TimeDistributed, Flatten
except ImportError:
    # TF 2.10 legacy path
    from tensorflow.keras.models import Sequential
    from tensorflow.keras.layers import Conv3D, LSTM, Dense, Dropout, Bidirectional, MaxPool3D, Activation, Reshape, SpatialDropout3D, BatchNormalization, TimeDistributed, Flatten

def load_model():
    model = Sequential()

    model.add(Conv3D(128, 3, input_shape=(75,46,140,1), padding='same'))
    model.add(Activation('relu'))
    model.add(MaxPool3D((1,2,2)))

    model.add(Conv3D(256, 3, padding='same'))
    model.add(Activation('relu'))
    model.add(MaxPool3D((1,2,2)))

    model.add(Conv3D(75, 3, padding='same'))
    model.add(Activation('relu'))
    model.add(MaxPool3D((1,2,2)))

    model.add(TimeDistributed(Flatten()))

    model.add(Bidirectional(LSTM(128, kernel_initializer='Orthogonal', return_sequences=True)))
    model.add(Dropout(.5))

    model.add(Bidirectional(LSTM(128, kernel_initializer='Orthogonal', return_sequences=True)))
    model.add(Dropout(.5))

    model.add(Dense(41, kernel_initializer='he_normal', activation='softmax'))

    
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    checkpoint_path = os.path.join(parent_dir, 'models', 'checkpoint')

    # Keras 3 (TF 2.16+) no longer supports loading raw TF1/TF2 checkpoints via
    # model.load_weights() — it only accepts .keras or .weights.h5 files.
    # Use tf.train.Checkpoint (low-level TF API) first; fall back to load_weights
    # for environments running an older Keras version that still supports it.
    loaded = False
    try:
        ckpt = tf.train.Checkpoint(model=model)
        ckpt.restore(checkpoint_path).expect_partial()
        # Force one forward pass to materialise the weights before returning.
        import numpy as _np
        _ = model(tf.zeros((1, 75, 46, 140, 1)), training=False)
        loaded = True
        print("[modelutil] Checkpoint restored via tf.train.Checkpoint.")
    except Exception as e1:
        print(f"[modelutil] tf.train.Checkpoint failed ({e1}), trying load_weights…")

    if not loaded:
        try:
            model.load_weights(checkpoint_path)
            loaded = True
            print("[modelutil] Checkpoint restored via load_weights.")
        except Exception as e2:
            raise RuntimeError(
                f"Cannot load LipNet weights from {checkpoint_path}.\n"
                f"tf.train.Checkpoint error: {e1}\n"
                f"load_weights error: {e2}"
            )

    return model
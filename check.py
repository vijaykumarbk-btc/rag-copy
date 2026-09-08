import numpy as np

embeddings = np.load("data/embeddings/new_embeddings/Cigna_ACDF_embeddings.npy")

print("Shape:", embeddings.shape)   # (num_chunks, embedding_dim)
print("Dtype:", embeddings.dtype)

print("\nFirst 5 rows:")
print(embeddings[:5])
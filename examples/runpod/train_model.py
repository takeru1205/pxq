#!/usr/bin/env python3
"""Train and evaluate PyTorch model on Spaceship Titanic dataset.

This script:
1. Loads data from /volume/data/spaceship-titanic/
2. Uses 20% of data for training/evaluation
3. Trains a simple PyTorch model
4. Saves metrics to /volume/results/

Requires: PyTorch, pandas, scikit-learn (pre-installed in runpod/pytorch image)
"""

import json
import os
import sys
import time

import pandas as pd
import torch
import torch.nn as nn
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, LabelEncoder
from torch.utils.data import DataLoader, TensorDataset


class SimpleClassifier(nn.Module):
    """Simple feedforward classifier for Titanic dataset."""

    def __init__(self, input_size: int):
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(input_size, 64),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(32, 2),  # Binary classification
        )

    def forward(self, x):
        return self.network(x)


def load_and_preprocess(data_dir: str, sample_ratio: float = 0.2):
    """Load and preprocess the Spaceship Titanic dataset.

    Args:
        data_dir: Path to data directory
        sample_ratio: Fraction of data to use (default: 20%)

    Returns:
        Preprocessed tensors and scaler
    """
    print(f"Loading data from {data_dir}")

    # Load training data
    train_df = pd.read_csv(os.path.join(data_dir, "train.csv"))
    print(f"Original dataset size: {len(train_df):,} rows")

    # Sample 20% of data
    if sample_ratio < 1.0:
        train_df = train_df.sample(frac=sample_ratio, random_state=42)
        print(f"Sampled dataset size: {len(train_df):,} rows ({sample_ratio*100:.0f}%)")

    # Handle missing values
    numeric_cols = train_df.select_dtypes(include=["int64", "float64"]).columns
    train_df[numeric_cols] = train_df[numeric_cols].fillna(
        train_df[numeric_cols].median()
    )

    # Encode categorical variables
    categorical_cols = ["HomePlanet", "CryoSleep", "Destination", "VIP"]
    label_encoders = {}
    for col in categorical_cols:
        if col in train_df.columns:
            le = LabelEncoder()
            train_df[col] = train_df[col].fillna("Unknown").astype(str)
            train_df[col] = le.fit_transform(train_df[col])
            label_encoders[col] = le

    # Prepare features and target
    feature_cols = [c for c in numeric_cols if c != "Transported"] + categorical_cols
    X = train_df[feature_cols].values
    y = train_df["Transported"].astype(int).values

    # Scale features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Convert to tensors
    X_tensor = torch.FloatTensor(X_scaled)
    y_tensor = torch.LongTensor(y)

    print(f"Features shape: {X_tensor.shape}")
    print(f"Target shape: {y_tensor.shape}")

    return X_tensor, y_tensor, scaler, feature_cols


def train_model(X_train, y_train, X_val, y_val, epochs=50, batch_size=32, lr=0.001):
    """Train the classifier model.

    Returns:
        Training metrics dictionary
    """
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    # Create data loaders
    train_dataset = TensorDataset(X_train, y_train)
    val_dataset = TensorDataset(X_val, y_val)
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size)

    # Initialize model
    model = SimpleClassifier(X_train.shape[1]).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)

    print(f"\nTraining for {epochs} epochs...")
    best_val_acc = 0.0
    start_time = time.time()

    for epoch in range(epochs):
        # Training
        model.train()
        train_loss = 0.0
        train_correct = 0
        train_total = 0

        for batch_X, batch_y in train_loader:
            batch_X, batch_y = batch_X.to(device), batch_y.to(device)

            optimizer.zero_grad()
            outputs = model(batch_X)
            loss = criterion(outputs, batch_y)
            loss.backward()
            optimizer.step()

            train_loss += loss.item()
            _, predicted = outputs.max(1)
            train_total += batch_y.size(0)
            train_correct += predicted.eq(batch_y).sum().item()

        # Validation
        model.eval()
        val_loss = 0.0
        val_correct = 0
        val_total = 0

        with torch.no_grad():
            for batch_X, batch_y in val_loader:
                batch_X, batch_y = batch_X.to(device), batch_y.to(device)
                outputs = model(batch_X)
                loss = criterion(outputs, batch_y)

                val_loss += loss.item()
                _, predicted = outputs.max(1)
                val_total += batch_y.size(0)
                val_correct += predicted.eq(batch_y).sum().item()

        train_acc = train_correct / train_total
        val_acc = val_correct / val_total

        if val_acc > best_val_acc:
            best_val_acc = val_acc

        if (epoch + 1) % 10 == 0 or epoch == 0:
            print(
                f"Epoch {epoch+1:3d}/{epochs}: "
                f"train_loss={train_loss/len(train_loader):.4f}, "
                f"train_acc={train_acc:.4f}, "
                f"val_acc={val_acc:.4f}"
            )

    elapsed_time = time.time() - start_time
    print(f"\nTraining completed in {elapsed_time:.1f} seconds")
    print(f"Best validation accuracy: {best_val_acc:.4f}")

    return {
        "epochs": epochs,
        "batch_size": batch_size,
        "learning_rate": lr,
        "best_val_accuracy": best_val_acc,
        "final_train_accuracy": train_acc,
        "final_val_accuracy": val_acc,
        "training_time_seconds": elapsed_time,
        "device": str(device),
    }


def main():
    print("=" * 60)
    print("PyTorch Training: Spaceship Titanic")
    print("=" * 60)

    # Configuration
    data_dir = "/kaggle/input/spaceship-titanic"
    results_dir = "/workspace"
    sample_ratio = 0.2  # Use 20% of data

    # Check data exists
    if not os.path.exists(data_dir):
        print(f"Error: Data directory not found: {data_dir}", file=sys.stderr)
        print("Run download_dataset.py first", file=sys.stderr)
        sys.exit(1)

    # Create results directory
    os.makedirs(results_dir, exist_ok=True)
    print(f"Results will be saved to: {results_dir}")

    # Load and preprocess data
    X, y, scaler, feature_cols = load_and_preprocess(data_dir, sample_ratio)

    # Split into train/validation
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    print(f"Train size: {len(X_train):,}, Validation size: {len(X_val):,}")

    # Train model
    metrics = train_model(
        X_train, y_train, X_val, y_val, epochs=50, batch_size=32, lr=0.001
    )

    # Add data info to metrics
    metrics["dataset"] = "spaceship-titanic"
    metrics["sample_ratio"] = sample_ratio
    metrics["train_samples"] = len(X_train)
    metrics["val_samples"] = len(X_val)
    metrics["num_features"] = len(feature_cols)

    # Save metrics
    metrics_path = os.path.join(results_dir, "metrics.json")
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"\nMetrics saved to: {metrics_path}")

    print("\n" + "=" * 60)
    print("Training completed successfully!")
    print("=" * 60)

    # Print summary
    print("\nSummary:")
    print(f"  Dataset: {metrics['dataset']}")
    print(f"  Sample ratio: {metrics['sample_ratio']*100:.0f}%")
    print(f"  Training samples: {metrics['train_samples']:,}")
    print(f"  Validation samples: {metrics['val_samples']:,}")
    print(f"  Best validation accuracy: {metrics['best_val_accuracy']:.4f}")
    print(f"  Training time: {metrics['training_time_seconds']:.1f}s")
    print(f"  Device: {metrics['device']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

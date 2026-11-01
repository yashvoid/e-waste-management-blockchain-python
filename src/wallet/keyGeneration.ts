import { secp256k1 } from "@noble/curves/secp256k1.js";
import { bytesToHex } from "../crypto/bytes";
import { compressedPublicKeyFromPrivateKey, walletAddressFromPublicKey } from "../crypto/secp256k1";

export interface GeneratedWallet {
  privateKey: Uint8Array;
  publicKeyHex: string;
  address: string;
}

export function generateWalletKeyPair(): GeneratedWallet {
  const privateKey = secp256k1.utils.randomSecretKey();
  if (!secp256k1.utils.isValidSecretKey(privateKey)) {
    throw new Error("Generated private key failed validation.");
  }
  const privateKeyHex = bytesToHex(privateKey);
  const publicKeyHex = compressedPublicKeyFromPrivateKey(privateKeyHex);
  const address = walletAddressFromPublicKey(publicKeyHex);
  return { privateKey, publicKeyHex, address };
}

export function derivePublicKeyAndAddress(privateKey: Uint8Array): {
  publicKeyHex: string;
  address: string;
} {
  if (!secp256k1.utils.isValidSecretKey(privateKey)) {
    throw new Error("Private key is invalid.");
  }
  const privateKeyHex = bytesToHex(privateKey);
  const publicKeyHex = compressedPublicKeyFromPrivateKey(privateKeyHex);
  const address = walletAddressFromPublicKey(publicKeyHex);
  return { publicKeyHex, address };
}

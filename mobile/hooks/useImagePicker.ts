import { useState } from 'react'
import { Alert, Platform } from 'react-native'
import * as ImagePicker from 'expo-image-picker'
import toast from '../utils/toast'
import {
  requestCameraPermission,
  requestImagePickerMediaPermission,
} from '../services/permissions'

interface UseImagePickerOptions {
  aspect?: [number, number]
  quality?: number
}

export function useImagePicker(options: UseImagePickerOptions = {}) {
  const { aspect = [1, 1], quality = 0.8 } = options
  const [photo, setPhoto] = useState<ImagePicker.ImagePickerAsset | null>(null)

  const takePhoto = async () => {
    const granted = await requestCameraPermission()

    if (!granted) {
      toast.info('Please allow camera access to take a photo')
      return
    }

    const result = await ImagePicker.launchCameraAsync({
      allowsEditing: true,
      aspect,
      quality,
      cameraType: ImagePicker.CameraType.front,
    })

    if (!result.canceled) {
      setPhoto(result.assets[0])
    }
  }

  const pickFromGallery = async () => {
    const granted = await requestImagePickerMediaPermission()

    if (!granted) {
      toast.info('Please allow photo library access to select a photo')
      return
    }

    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      allowsEditing: true,
      aspect,
      quality,
    })

    if (!result.canceled) {
      setPhoto(result.assets[0])
    }
  }

  const showPicker = () => {
    Alert.alert(
      'Photo',
      'Choose an option',
      [
        { text: 'Take Photo', onPress: takePhoto },
        {
          text:
            Platform.OS === 'ios'
              ? 'Choose from Library'
              : 'Choose from Gallery',
          onPress: pickFromGallery,
        },
        { text: 'Cancel', style: 'cancel' },
      ],
      { cancelable: true }
    )
  }

  const clearPhoto = () => setPhoto(null)

  /** Restore a previously chosen photo (e.g. from a session draft) without
   * opening the picker. Only uri/mimeType/fileName are known post-restore —
   * the fields the upload path uses. */
  const restorePhoto = (asset: {
    uri: string
    mimeType?: string
    fileName?: string
  }) => {
    setPhoto({
      uri: asset.uri,
      mimeType: asset.mimeType,
      fileName: asset.fileName ?? null,
      width: 0,
      height: 0,
    } as ImagePicker.ImagePickerAsset)
  }

  return { takePhoto, pickFromGallery, showPicker, photo, clearPhoto, restorePhoto }
}

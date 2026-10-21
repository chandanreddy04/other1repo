import Toast from 'react-native-toast-message'

const toast = {
  success(message: string, detail?: string) {
    Toast.show({ type: 'success', text1: message, text2: detail })
  },
  error(message: string, detail?: string) {
    Toast.show({
      type: 'error',
      text1: message,
      text2: detail,
      visibilityTime: 4000,
    })
  },
  info(message: string, detail?: string) {
    Toast.show({ type: 'info', text1: message, text2: detail })
  },
}

export default toast

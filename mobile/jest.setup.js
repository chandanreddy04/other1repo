// Replace the native AsyncStorage module with its in-memory jest mock so
// unit tests can exercise persistence logic deterministically.
jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)

// The Bugsnag stack is native-backed; tests exercise services/errorReporting.ts's own
// logic against these stand-ins (see services/errorReporting.test.ts).
jest.mock('@bugsnag/expo', () => ({
  __esModule: true,
  default: {
    start: jest.fn(),
    notify: jest.fn(),
    leaveBreadcrumb: jest.fn(),
    setUser: jest.fn(),
    isStarted: jest.fn(() => false),
  },
}))
jest.mock('expo-updates', () => ({
  channel: null,
  updateId: null,
  runtimeVersion: null,
}))
jest.mock('@react-native-community/netinfo', () => ({
  __esModule: true,
  default: {
    fetch: jest.fn(() =>
      Promise.resolve({
        isConnected: true,
        isInternetReachable: true,
        type: 'wifi',
      })
    ),
  },
}))

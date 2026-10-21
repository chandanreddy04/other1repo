const { RuleTester } = require('eslint')
const tsParser = require('@typescript-eslint/parser')
const rule = require('./swallowed-errors')

const tester = new RuleTester({
  languageOptions: {
    parser: tsParser,
    ecmaVersion: 2022,
    sourceType: 'module',
  },
})

const SWALLOW = /swallows the error/
const CONSOLE = /must be reported/

tester.run('swallowed-errors', rule, {
  valid: [
    // reported
    "try { f() } catch (err) { notify(err, 'x.y') }",
    "p.catch(err => notify(err, 'x.y'))",
    // benign, comment inside the handler
    'try { f() } catch { /* benign: expected */ }',
    'try { f() } catch {\n  // benign: expected\n}',
    'p.catch(() => {\n  // benign: expected\n})',
    'p.catch(() => /* benign: expected */ null)',
    // benign, comment on the line before the handler
    '// benign: expected\np.catch(() => null)',
    // a handler that uses its argument for something other than console is fine
    'p.catch(err => setError(err.message))',
    'try { f() } catch (err) { setError(err) }',
    'try { f() } catch (_err) { /* benign: expected */ return false }',
    // a shorthand property IS a read of the binding
    'try { f() } catch (err) { set({ err }) }',
    // a named handler receives the error — it is judged where it is defined
    'p.catch(handleError)',
    'p.catch(setError)',
    '// benign: expected\np.catch(noop)',
  ],
  invalid: [
    { code: 'try { f() } catch {}', errors: [{ message: SWALLOW }] },
    {
      code: 'try { f() } catch { return false }',
      errors: [{ message: SWALLOW }],
    },
    {
      code: 'try { f() } catch { /* not marked */ }',
      errors: [{ message: SWALLOW }],
    },
    { code: 'p.catch(() => {})', errors: [{ message: SWALLOW }] },
    { code: 'p.catch(() => null)', errors: [{ message: SWALLOW }] },
    { code: 'p.catch(function () {})', errors: [{ message: SWALLOW }] },
    {
      code: 'try { f() } catch (err) { return false }',
      errors: [{ message: SWALLOW }],
    },
    { code: 'p.catch(e => {})', errors: [{ message: SWALLOW }] },
    { code: 'p.catch(e => setLoading(false))', errors: [{ message: SWALLOW }] },
    {
      code: "try { f() } catch (err) { console.error('x', err) }",
      errors: [{ message: CONSOLE }],
    },
    {
      code: "try { f() } catch (err) { console.warn('x', err); return null }",
      errors: [{ message: CONSOLE }],
    },
    {
      code: "p.catch(err => console.error('x', err))",
      errors: [{ message: CONSOLE }],
    },
    {
      code: "p.catch(err => { console.log('x', err) })",
      errors: [{ message: CONSOLE }],
    },
    // same-named property keys, member names and shadowing params are not reads
    {
      code: "try { f() } catch (error) { set({ error: 'x' }) }",
      errors: [{ message: SWALLOW }],
    },
    {
      code: 'try { f() } catch (err) { use(state.err) }',
      errors: [{ message: SWALLOW }],
    },
    {
      code: "try { f() } catch (error) { toast.error('x') }",
      errors: [{ message: SWALLOW }],
    },
    {
      code: 'try { f() } catch (err) { items.forEach(err => use(err)) }',
      errors: [{ message: SWALLOW }],
    },
    {
      code: 'try { f() } catch (err) { try { g() } catch (err) { use(err) } }',
      errors: [{ message: SWALLOW }],
    },
    { code: 'p.catch(noop)', errors: [{ message: SWALLOW }] },
    { code: 'p.catch(console.error)', errors: [{ message: CONSOLE }] },
  ],
})

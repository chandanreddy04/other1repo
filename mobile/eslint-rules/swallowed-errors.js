/**
 * local/swallowed-errors (loaded by eslint.config.mjs; tested by
 * swallowed-errors.test.js with ESLint's RuleTester).
 *
 * local/swallowed-errors — a caught error is either reported (notify) or
 * explicitly benign. Flags:
 *   1. `catch` blocks and promise `.catch` handlers that swallow the error
 *      (empty body, a handler that ignores its argument, `.catch(noop)`)
 *      without a `benign: <reason>` comment inside the handler or on the line
 *      before it. "Uses its argument" means READS the binding: a property key
 *      (`{ error: 'x' }`), a member name (`toast.error(...)`, `state.err`) or a
 *      nested function/catch that rebinds the same name does not count;
 *   2. `console.error|warn|log` inside any catch block or `.catch` handler
 *      (including `.catch(console.error)`) — that is not a report; use
 *      notify() from services/errorReporting.ts.
 */
const swallowedErrorsRule = {
  meta: {
    type: 'problem',
    docs: { description: 'caught errors are reported or marked benign' },
    schema: [],
  },
  create(context) {
    const source = context.sourceCode
    const hasBenignComment = node => {
      const inside = source.getCommentsInside(node)
      // A comment on the line before the handler, or earlier on the same
      // line, also counts — `.catch(() => null)` has no body to put it in.
      const adjacent = source
        .getAllComments()
        .filter(
          c =>
            c.loc.end.line === node.loc.start.line - 1 ||
            (c.loc.end.line === node.loc.start.line &&
              c.range[1] <= node.range[0])
        )
      return [...inside, ...adjacent].some(c => c.value.includes('benign:'))
    }
    const isConsoleCall = node =>
      node.type === 'CallExpression' &&
      node.callee.type === 'MemberExpression' &&
      node.callee.object.type === 'Identifier' &&
      node.callee.object.name === 'console' &&
      ['error', 'warn', 'log'].includes(node.callee.property.name)
    const consoleCallsIn = node => {
      const found = []
      const visit = n => {
        if (!n || typeof n.type !== 'string') return
        if (isConsoleCall(n)) found.push(n)
        for (const key of Object.keys(n)) {
          if (key === 'parent' || key === 'loc' || key === 'range') continue
          const child = n[key]
          if (Array.isArray(child)) child.forEach(visit)
          else if (child && typeof child.type === 'string') visit(child)
        }
      }
      visit(node)
      return found
    }
    const reportConsole = node =>
      context.report({
        node,
        message:
          'A caught error must be reported: notify(err, "<module>.<action>") from services/errorReporting.ts (it echoes to the console in dev). If ignoring it is correct, drop the console call and add `// benign: <reason>`.',
      })
    const reportSwallow = node =>
      context.report({
        node,
        message:
          'This swallows the error. Report it with notify(err, "<module>.<action>"), or explain why that is fine with a `// benign: <reason>` comment inside the handler.',
      })
    const isFunction = n =>
      n.type === 'ArrowFunctionExpression' ||
      n.type === 'FunctionExpression' ||
      n.type === 'FunctionDeclaration'
    // A nested function parameter or catch clause with the same name shadows
    // the binding — references inside it are not reads of the caught error.
    const rebinds = (n, name) =>
      (isFunction(n) &&
        n.params.some(p => p.type === 'Identifier' && p.name === name)) ||
      (n.type === 'CatchClause' &&
        n.param !== null &&
        n.param.type === 'Identifier' &&
        n.param.name === name)
    const referencesName = (node, name) => {
      let found = false
      const visit = (n, parent, key) => {
        if (found || !n || typeof n.type !== 'string') return
        if (n.type === 'Identifier' && n.name === name) {
          const propertyKey =
            parent &&
            parent.type === 'Property' &&
            key === 'key' &&
            !parent.computed
          const memberName =
            parent &&
            parent.type === 'MemberExpression' &&
            key === 'property' &&
            !parent.computed
          if (!propertyKey && !memberName) found = true
          return
        }
        if (rebinds(n, name)) return
        for (const k of Object.keys(n)) {
          if (k === 'parent' || k === 'loc' || k === 'range') continue
          const child = n[k]
          if (Array.isArray(child)) child.forEach(c => visit(c, n, k))
          else if (child && typeof child.type === 'string') visit(child, n, k)
        }
      }
      visit(node, null, null)
      return found
    }
    // A handler swallows its error when it has no binding, an empty body, or
    // a bound identifier it never reads (`catch (err) { return false }`).
    const usesError = (param, body) =>
      param !== null && param.type === 'Identifier'
        ? referencesName(body, param.name)
        : param !== null
    return {
      CatchClause(node) {
        consoleCallsIn(node.body).forEach(reportConsole)
        const swallows =
          node.body.body.length === 0 || !usesError(node.param, node.body)
        if (swallows && !hasBenignComment(node.body)) reportSwallow(node)
      },
      CallExpression(node) {
        const callee = node.callee
        if (
          callee.type !== 'MemberExpression' ||
          callee.property.type !== 'Identifier' ||
          callee.property.name !== 'catch' ||
          node.arguments.length === 0
        )
          return
        const handler = node.arguments[0]
        if (
          handler.type !== 'ArrowFunctionExpression' &&
          handler.type !== 'FunctionExpression'
        ) {
          // `.catch(console.error)` is not a report; `.catch(noop)` is a swallow.
          // Any other named handler receives the error — it is judged where
          // it is defined.
          if (
            handler.type === 'MemberExpression' &&
            handler.object.type === 'Identifier' &&
            handler.object.name === 'console'
          ) {
            reportConsole(handler)
          } else if (
            handler.type === 'Identifier' &&
            /^(noop|noOp|_)$/.test(handler.name) &&
            !hasBenignComment(node)
          ) {
            reportSwallow(handler)
          }
          return
        }
        consoleCallsIn(handler.body).forEach(reportConsole)
        const param = handler.params.length === 0 ? null : handler.params[0]
        const emptyBody =
          handler.body.type === 'BlockStatement' &&
          handler.body.body.length === 0
        if (
          (emptyBody || !usesError(param, handler.body)) &&
          !hasBenignComment(handler)
        ) {
          reportSwallow(handler)
        }
      },
    }
  },
}

module.exports = swallowedErrorsRule

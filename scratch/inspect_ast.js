const fs = require('fs');
const acorn = require('acorn');

const code = fs.readFileSync('scratch/live_script_11.js', 'utf8');
const ast = acorn.parse(code, { ecmaVersion: 'latest', sourceType: 'script', locations: true });

console.log('Total top-level body statements: ' + ast.body.length);
ast.body.forEach((node, i) => {
    if (node.type !== 'FunctionDeclaration') {
        const line = node.loc.start.line;
        const src = code.split('\n')[line - 1].trim().slice(0, 90);
        console.log(`[${i}] Line ${line}: ${node.type} -> ${src}`);
    }
});

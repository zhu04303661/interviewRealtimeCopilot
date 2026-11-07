export function createLocalAuthUi({ React, Button, Input, Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter }) {
  const h = React.createElement;
  const labels = {
    signIn: 'Sign in locally',
    register: 'Create a local account',
    activate: 'Activate admin',
  };

  function field(label, name, props) {
    return h('label', { className: 'block space-y-1.5 text-body-sm font-medium' },
      h('span', null, label),
      h(Input, { name, required: true, ...props }),
    );
  }

  function LocalSignInEntry({ onSignedIn }) {
    const [open, setOpen] = React.useState(false);
    const [mode, setMode] = React.useState('signIn');
    const [setupRequired, setSetupRequired] = React.useState(false);
    const [busy, setBusy] = React.useState(false);
    const [error, setError] = React.useState('');

    function changeMode(next) {
      setMode(next);
      setError('');
    }

    function changeOpen(next) {
      if (busy) return;
      setOpen(next);
      if (next) {
        changeMode('signIn');
        void window.localAuth.status().then((status) => setSetupRequired(status.setupRequired))
          .catch(() => setError('The local account store could not be read.'));
      }
    }

    async function submit(event) {
      event.preventDefault();
      const form = event.currentTarget;
      const input = Object.fromEntries(new FormData(form));
      form.querySelectorAll('input[type=password]').forEach((field) => { field.value = ''; });
      setBusy(true);
      setError('');
      try {
        await window.localAuth[mode](input);
        setOpen(false);
        onSignedIn();
      } catch (failure) {
        setError(failure.message);
      } finally {
        setBusy(false);
      }
    }

    return h(React.Fragment, null,
      h(Button, { type: 'button', className: 'h-10 w-9/12 gap-2 rounded-md', onClick: () => changeOpen(true) }, 'Sign in locally'),
      h(Dialog, { open, onOpenChange: changeOpen },
        h(DialogContent, null,
          h(DialogHeader, null,
            h(DialogTitle, null, labels[mode]),
            h(DialogDescription, null, 'Sign in to your workspace on this Mac.'),
          ),
          h('form', { key: mode, onSubmit: submit, className: 'space-y-4', 'data-local-auth-form': mode },
            mode !== 'activate' && field('Username', 'username', { autoComplete: 'username', maxLength: 32, disabled: busy }),
            mode === 'activate' && field('One-time setup code', 'code', { type: 'password', autoComplete: 'off', maxLength: 32, disabled: busy }),
            field(mode === 'activate' ? 'New password' : 'Password', mode === 'activate' ? 'newPassword' : 'password',
              { type: 'password', autoComplete: mode === 'signIn' ? 'current-password' : 'new-password',
                minLength: mode === 'signIn' ? undefined : 15, maxLength: 256, disabled: busy }),
            error && h('p', { role: 'alert', className: 'text-err text-body-sm' }, error),
            h(DialogFooter, null, h(Button, { type: 'submit', disabled: busy }, busy ? 'Please wait…' : labels[mode])),
          ),
          h('div', { className: 'flex flex-wrap gap-2' },
            mode !== 'signIn' && h(Button, { variant: 'ghost', size: 'sm', disabled: busy, onClick: () => changeMode('signIn') }, 'Back to sign in'),
            mode !== 'register' && h(Button, { variant: 'ghost', size: 'sm', disabled: busy, onClick: () => changeMode('register') }, 'Create account'),
            setupRequired && mode !== 'activate' && h(Button, { variant: 'ghost', size: 'sm', disabled: busy, onClick: () => changeMode('activate') }, 'Activate admin'),
          ),
        ),
      ),
    );
  }

  function LocalAccountPanel({ account }) {
    const [accounts, setAccounts] = React.useState(null);
    const [error, setError] = React.useState('');
    React.useEffect(() => {
      if (account.role !== 'admin') return;
      let active = true;
      void window.localAuth.listAccounts().then((list) => {
        if (active) setAccounts(list);
      }).catch((failure) => {
        if (active) setError(failure.message);
      });
      return () => { active = false; };
    }, [account.role]);
    return h('section', { className: 'space-y-4', 'data-local-account': account.username },
      h('div', { className: 'border-hairline rounded-lg border p-4' },
        h('p', { className: 'text-body text-text-1 font-semibold' }, account.username),
        h('p', { className: 'text-body-sm text-text-2' }, account.role === 'admin' ? 'Local administrator' : 'Local member'),
      ),
      account.role === 'admin' && h('div', { className: 'border-hairline space-y-2 rounded-lg border p-4' },
        h('h3', { className: 'text-body text-text-1 font-semibold' }, 'Local accounts'),
        error && h('p', { role: 'alert', className: 'text-err' }, error),
        accounts && h('ul', { className: 'text-body-sm space-y-1' },
          accounts.map((item) => h('li', { key: item.username }, item.username + ' · ' + item.role))),
      ),
    );
  }

  return { LocalSignInEntry, LocalAccountPanel };
}
